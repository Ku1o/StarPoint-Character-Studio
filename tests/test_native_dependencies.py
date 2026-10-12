"""Verified native roots do not turn partial source evidence into readiness."""
import copy
import hashlib
import json
import os
import struct
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_dependencies as deps
import native_gameplay as native
from studio_core import ProjectStore
from test_native_gameplay import pack, row


def fixture():
    definitions = pack()
    character = definitions['characters']['10']
    cr = character['records']['character']['selected']['10']['rows'][0]
    cr[2], cr[3], cr[6], cr[9], cr[14], cr[28] = '4', '3', '4', '(None)', '', 'pedestal_reference'
    character['records']['action_skill']['rows'][0]['fields'][3] = 'true'
    character['records']['action_skill']['rows'][0]['fields'][7] = 'battle/action/skill/fixture_1'
    source = {'version': definitions['version'], 'character': character, 'blankRows': definitions['blankRows']}
    value = {'schema': native.SCHEMA, 'source': {'data': source, 'sha256': native.digest(source)},
             'skills': copy.deepcopy(character['records']['action_skill']['rows']),
             'leader': {'sourceKey': cr[17], 'rows': copy.deepcopy(character['records']['leader_ability']['selected'][cr[17]]['rows'])},
             'abilities': [{'slot': index+1, 'sourceKey': key, 'rows': copy.deepcopy(character['records']['abilities']['selected'][key]['rows'])}
                           for index, key in enumerate(cr[19:25])]}
    return {'nativeGameplay': value}


def condition_command(conditions, hit=None, check=None):
    return ['CreateCondition', -17, conditions, [{'min': 1, 'max': 1}],
            ['GenericConditionHitEffect'] if hit is None else hit, False, False, 'marker', check, False, 0, [], False]


def unique_table(icon='battle/unique/icon', direction='0'):
    import bridge
    import wf_mod_tool as mod
    fields = ['unique_fixture', '状态', icon, '60', '(None)', '(None)', '(None)', '(None)', '', 'true', 'false', direction]
    ordered = mod.OrderedMap(deps.UNIQUE_TABLE, ['123'], [(','.join(fields) + '\n').encode()], Path('<fixture>'))
    return mod.build_orderedmap(ordered)


def orderedmap_raw(keys, compressed_rows, *, pairs=None, index_tail=b'', row_tail=b'', compressed_index_tail=b''):
    key_data, row_data, offsets = b'', b'', []
    for key, row in zip(keys, compressed_rows):
        key_data += key.encode(); row_data += row
        offsets.append((len(key_data), len(row_data)))
    index = struct.pack('<I', len(keys)) + b''.join(struct.pack('<II', *item) for item in (pairs or offsets)) + key_data + index_tail
    compressed = zlib.compress(index) + compressed_index_tail
    return struct.pack('<I', len(compressed)) + compressed + row_data + row_tail


class NativeDependencyTests(unittest.TestCase):
    def test_nested_invalid_enum_tags_return_unknown_without_mutation(self):
        bad = condition_command([[["ACAttackPoint"]]])
        before = copy.deepcopy(bad)
        result = deps.resolve_command_resources(bad)
        self.assertEqual(bad, before)
        self.assertTrue(any("未知AdditionalConditionKind" in p["reason"] for p in result["problems"]))
        attack = ["CreateNormalAttack"] + [None] * 15
        attack[15] = [["Fine"]]
        before = copy.deepcopy(attack)
        result = deps.resolve_command_resources(attack)
        self.assertEqual(attack, before)
        self.assertTrue(any("结构无效" in p["reason"] for p in result["problems"]))
        result = deps.resolve_command_resources(["ShowEffect", 0, ["SpecifyEffectByElement", "battle/effect", 10**400]])
        self.assertTrue(result["problems"])
        bomb = ["CreateBombMultiball", 0, "../bad", ["E1", ["SpecifyEffectDirectly", "battle/ready"]],
                ["SpecifyEffectDirectly", "battle/a"], ["SpecifyEffectDirectly", "battle/b"]]
        result = deps.resolve_command_resources(bomb)
        self.assertTrue(any(p["domain"] == "summon" and "路径无效" in p["reason"] for p in result["problems"]))

    def test_auto_roots_byte_identity_and_role_source_are_read_only(self):
        project = fixture()
        before = copy.deepcopy(project)
        receipt = deps.extract_native_roots(project)
        self.assertEqual(project, before)
        self.assertEqual(receipt['element'], 3)
        self.assertEqual(receipt['sourceIdentity']['sha256'], project['nativeGameplay']['source']['sha256'])
        skills = [r for r in receipt['roots'] if r['category'] == 'skill']
        self.assertEqual({r['roles'][0] for r in skills}, {'main', 'unison', 'leader'})
        self.assertTrue(all(r['logical'].endswith('.action.dsl.amf3.deflate') for r in skills))
        bodies = [r for r in receipt['roots'] if r['category'] == 'pixelart']
        self.assertEqual({r['roles'][0] for r in bodies}, {'main', 'leader'})
        self.assertIn('character/fixture/ui/square_1', receipt['domains']['ui']['roots'])
        self.assertNotIn('character/fixture/ui/square_132_132_1', receipt['domains']['ui']['roots'])
        cutins = [r for r in receipt['roots'] if r['category'] == 'cutin']
        self.assertTrue(all(r['bucket'] == 'characters' and r['layer'] == 'independent' for r in cutins))
        self.assertFalse(receipt['complete'])
        self.assertFalse(receipt['gameReady'])
        self.assertEqual(receipt['domains']['ability']['status'], 'pending')

    def test_manual_completeness_and_wrong_source_hash_do_not_close_graph(self):
        project = fixture()
        project['dependencyScope'] = {'complete': True, 'domains': {name: {'status': 'included'} for name in deps.DOMAINS}}
        receipt = deps.extract_native_roots(project)
        self.assertFalse(receipt['complete'])
        project['nativeGameplay']['source']['data']['version'] = 'untracked'
        bad = deps.extract_native_roots(project)
        self.assertFalse(bad['roots'])
        self.assertTrue(bad['problems'])
        self.assertEqual(bad['domains']['pixelart']['status'], 'pending')

    def test_every_skill_version_and_switch_row_uses_the_actual_table_column(self):
        project = fixture()
        native_value = project['nativeGameplay']
        source = native_value['source']['data']
        cr = source['character']['records']['character']['selected']['10']['rows'][0]
        cr[9], cr[14] = '4', 'fixture_switch'
        source['character']['records']['switched_skill'] = {'rows': [{'inner_key': '1', 'fields': ['battle/action/switch/real', '0']}]}
        native_value['source']['sha256'] = native.digest(source)
        second = copy.deepcopy(native_value['skills'][0])
        second['inner_key'] = '2'; second['fields'][7] = 'battle/action/skill/fixture_2'; second['fields'][3] = 'false'
        native_value['skills'].append(second)
        receipt = deps.extract_native_roots(project)
        self.assertEqual(set(receipt['forms']), {'1', '2', 'all', '0'})
        self.assertEqual(receipt['switches'], ['fixture_switch', 'base'])
        switched = [r for r in receipt['roots'] if r['switches'] == ['fixture_switch']]
        self.assertEqual({r['logical'] for r in switched}, {'battle/action/switch/real.action.dsl.amf3.deflate'})
        self.assertFalse(any(r['roles'] == ['unison'] and r['forms'] == ['2'] and r['switches'] == ['base'] for r in receipt['roots'] if r['category'] == 'skill'))

    def test_invoke629_uses_ability_and_leader_offset_and_preserves_bad_rows(self):
        project = fixture()
        value = project['nativeGameplay']
        for kind, group in [('leader_ability', value['leader']), ('ability', value['abilities'][0])]:
            base = native.describe.layout(kind)['blocks']['instant_content']
            group['rows'][0][base] = '629'
            group['rows'][0][base+24] = 'battle/action/invoke/' + kind
        value['abilities'][1]['rows'][0][1] = ''
        receipt = deps.extract_native_roots(project)
        roots = receipt['domains']['ability']['roots']
        self.assertEqual(set(roots), {'battle/action/invoke/leader_ability.action.dsl.amf3.deflate', 'battle/action/invoke/ability.action.dsl.amf3.deflate'})
        self.assertTrue(any('true/false' in p['reason'] for p in receipt['problems']))
        self.assertEqual(value['abilities'][1]['rows'][0][1], '')
        self.assertFalse(receipt['complete'])

    def test_first_row_controls_whole_ability_group_unison_admission(self):
        project = fixture()
        group = project['nativeGameplay']['abilities'][0]
        first = group['rows'][0]
        first[1] = 'false'
        second = copy.deepcopy(first)
        base = native.describe.layout('ability')['blocks']['instant_content']
        second[1] = 'true'; second[base] = '629'; second[base+24] = 'battle/action/invoke/group'
        group['rows'].append(second)
        receipt = deps.extract_native_roots(project)
        roots = [r for r in receipt['roots'] if r['category'] == 'ability']
        self.assertEqual({r['roles'][0] for r in roots}, {'main', 'leader'})
        first[1] = 'true'; second[1] = 'false'
        receipt = deps.extract_native_roots(project)
        roots = [r for r in receipt['roots'] if r['category'] == 'ability']
        self.assertEqual({r['roles'][0] for r in roots}, {'main', 'leader', 'unison'})

    def test_pf_three_levels_only_with_source_evidence_and_leader_scope(self):
        project = fixture()
        data = project['nativeGameplay']['source']['data']
        data['character']['records']['power_flip'] = {'key': 'special', 'rows': [['battle/pf/one', 'battle/pf/two', 'battle/pf/three']],
                                                    'source': {'logical_path': 'master/skill/power_flip_action.orderedmap', 'sha256': 'a'*64}}
        project['nativeGameplay']['source']['sha256'] = native.digest(data)
        receipt = deps.extract_native_roots(project)
        pf = [r for r in receipt['roots'] if r['category'] == 'powerFlip']
        self.assertEqual(len(pf), 3)
        self.assertTrue(all(r['roles'] == ['leader'] for r in pf))
        self.assertEqual(receipt['domains']['powerFlip']['status'], 'included')
        self.assertFalse(deps.extract_native_roots(project, roles=['unison'])['domains']['powerFlip']['roots'])
        del data['character']['records']['power_flip']['source']['sha256']
        project['nativeGameplay']['source']['sha256'] = native.digest(data)
        bad = deps.extract_native_roots(project)
        self.assertEqual(bad['domains']['powerFlip']['status'], 'pending')

    def test_element255_uses_definition_and_colorless_hit_does_not_invent_texture(self):
        command = ['CreateNormalAttack', 0, 255] + [None]*12 + [['Coarse'], False]
        receipt = deps.resolve_command_resources(command, 3)
        self.assertEqual(receipt['references'][0]['logical'], 'battle/effect/hit/normal_damage/coarse/coarse_green/coarse_green')
        self.assertTrue(receipt['handled'])
        self.assertFalse(receipt['problems'])
        unknown = deps.resolve_command_resources(command)
        self.assertTrue(unknown['problems'][0]['dynamic'])
        self.assertFalse(unknown['references'])
        colorless = deps.resolve_command_resources(command, 6)
        self.assertFalse(colorless['references'])
        self.assertIn('colorless', colorless['problems'][0]['reason'])

    def test_by_element_formula_and_generic_condition_implicit_resources(self):
        effect = ['ShowEffect', 0, ['SpecifyEffectByElement', 'battle/effect/element', 255]]
        self.assertEqual(deps.resolve_command_resources(effect, 5)['references'][0]['logical'], 'battle/effect/element/element_black/element_black')
        command = condition_command([['ACSkillDamage', []], ['ACToleranceOfElement', []], ['ACComboBoost', []], ['ACComboRestriction', []]])
        receipt = deps.resolve_command_resources(command, 3)
        self.assertTrue(receipt['handled'])
        self.assertFalse(receipt['problems'])
        self.assertEqual(len(receipt['references']), 18)  # all14defence + generic combo +3UI
        self.assertEqual(sum(r['context']['layer'] == 1 for r in receipt['references']), 3)
        self.assertFalse(deps.resolve_command_resources(condition_command([['ACSkillDamage', []]]))['references'])
        unique = deps.resolve_command_resources(condition_command([['ACUnique', 123]]))
        self.assertTrue(unique['problems'][0]['dynamic'])
        self.assertFalse(unique['references'])

    def test_unknown_conditions_and_invalid_effect_paths_remain_unresolved(self):
        for command in (condition_command([['FutureCondition', []]]),
                        condition_command([], ['SpecifyConditionHitEffectDirectly', ['SpecifyEffectDirectly', '../outside']]),
                        ['ShowEffect', 0, ['FutureEffect', 'filename']],
                        ['CreateNormalAttack', 0, 0] + [None]*12 + [['Fine'], False]):
            with self.subTest(command=command):
                receipt = deps.resolve_command_resources(command, 3)
                self.assertTrue(receipt['problems'])
                self.assertFalse(receipt['references'])

    def test_dsl_wrapper_callbacks_and_trace_payload_have_no_guessed_resources(self):
        condition = ['Command', condition_command([['ACSkillDamage', []]])]
        show = ['Command', ['ShowEffect', 0, ['SpecifyEffectDirectly', 'battle/effect/real']]]
        tree = ['Block', [['Command', ['Trace', ['Command', ['ShowEffect', 0, ['SpecifyEffectDirectly', 'battle/effect/fake']]]]],
                          ['Event', ['Wait', 0, 10, ['Block', [condition, show]]]]]]
        receipt = deps.resolve_dsl_resources(tree, 3)
        self.assertEqual([r['logical'] for r in receipt['references']], ['battle/effect/real'])
        self.assertEqual(len(receipt['handledPointers']), 2)
        self.assertTrue(all('/1/1/1/3/1/' in pointer for pointer in receipt['handledPointers']))

    def test_timed_conditions_follow_runtime_direction_without_claiming_preload(self):
        for condition in ('0', '1', '214', '28'):
            project = fixture()
            value = project['nativeGameplay']['abilities'][0]['rows'][0]
            base = native.describe.layout('ability')['blocks']['instant_content']
            value[base] = condition; value[base+4:base+6] = ['1', '2']
            before = deps.canonical(project)
            result = deps.extract_native_roots(project)
            roots = [r for r in result['roots'] if r['category'] == 'ability']
            self.assertEqual({r['logical'] for r in roots}, {'battle/effect/hit/condition/buff/buff'})
            self.assertTrue(all(r['origin'] == 'runtime-implicit' for r in roots))
            self.assertFalse(result['complete'])
            self.assertEqual(deps.canonical(project), before)
            value[base+4:base+6] = ['-1', '1']
            roots = deps.extract_native_roots(project)['domains']['ability']['roots']
            self.assertEqual(set(roots), {'battle/effect/hit/condition/buff/buff', 'battle/effect/hit/condition/debuff/debuff'})

    def test_generated_damage_colors_and_actual_shared_preload_are_not_character_name_guesses(self):
        for number in (251, 252, 256, 286, 316, 317, 351, 352, 387):
            project = fixture()
            fields = project['nativeGameplay']['abilities'][0]['rows'][0]
            base = native.describe.layout('ability')['blocks']['instant_content']
            fields[base] = str(number)
            result = deps.extract_native_roots(project)
            color = deps.COLORS[(number - (251 if number <= 286 else 316)) % 6]
            expected = {f'battle/effect/ability_damage/ability_damage_{color}/ability_damage_{part}_{color}' for part in ('hit', 'player', 'shot')}
            self.assertEqual(set(result['domains']['ability']['roots']), expected)
            self.assertTrue(set(deps.INAHO_PRELOAD).issubset(result['domains']['shared']['roots']))
            self.assertFalse(result['complete'])

    def test_barrier_and_disguise_hp_use_real_runtime_resource_kinds(self):
        project = fixture()
        fields = project['nativeGameplay']['leader']['rows'][0]
        blocks = native.describe.layout('leader_ability')['blocks']
        fields[blocks['instant_content']] = '227'
        fields[blocks['during_content']] = '156'
        result = deps.extract_native_roots(project)
        self.assertEqual(set(result['domains']['ability']['roots']), {'battle/effect/hit/condition/barrier/barrier_ball', 'battle/effect/hit/condition/barrier/breaking_barrier'})
        roots = [r for r in result['roots'] if r['logical'] == 'battle/common/disguise_hp']
        self.assertTrue(roots)
        self.assertTrue(all(r['kind'] == 'sprite-sheet' and r['roles'] == ['leader'] for r in roots))

    def test_unique_icon_and_enemy_hit_come_from_hashed_native_bytes(self):
        raw = unique_table(direction='1')
        refs = {deps.UNIQUE_TABLE: raw}
        command = condition_command([['ACUnique', 123, []]])
        result = deps.resolve_command_resources(command, reference_files=refs)
        self.assertFalse(result['problems'])
        self.assertEqual(result['references'][0]['logical'], 'battle/unique/icon')
        self.assertEqual(result['references'][0]['context']['kind'], 'image')
        self.assertEqual(result['references'][0]['definitionEvidence']['sha256'], hashlib.sha256(raw).hexdigest())
        project = fixture()
        fields = project['nativeGameplay']['abilities'][0]['rows'][0]
        base = native.describe.layout('ability')['blocks']['instant_content']
        fields[base] = '413'; fields[base+21] = '123'
        result = deps.extract_native_roots(project, refs)
        self.assertEqual(set(result['domains']['ability']['roots']), {'battle/unique/icon', 'battle/effect/hit/condition/debuff/debuff'})
        self.assertFalse(result['complete'])
        self.assertEqual(refs[deps.UNIQUE_TABLE], raw)
        for invalid in ({deps.UNIQUE_TABLE: b'not-a-table'}, {deps.UNIQUE_TABLE: unique_table('../outside')}, {deps.UNIQUE_TABLE: unique_table(direction='2')}):
            missing = deps.extract_native_roots(project, invalid)
            self.assertTrue(any(p['domain'] == 'ability' for p in missing['problems']))

    def test_orderedmap_bounds_index_and_selected_row_before_expansion(self):
        bomb = zlib.compress(b'a'*1024)
        row_bomb = orderedmap_raw(['123'], [bomb])
        index_bomb = orderedmap_raw(['k'*1024], [zlib.compress(b'ordinary')])
        for raw in (row_bomb, index_bomb):
            self.assertLess(len(raw), 128)
            with self.subTest(index=raw == index_bomb), mock.patch.object(deps, 'LIMIT', 128):
                reader = deps._DefinitionReader({deps.UNIQUE_TABLE: raw})
                with self.assertRaisesRegex(ValueError, '解压输出超限'):
                    reader.row(deps.UNIQUE_TABLE, '123')
                result = deps.resolve_command_resources(condition_command([['ACUnique', 123, []]]), reference_files={deps.UNIQUE_TABLE: raw})
                self.assertFalse(result['references'])
                self.assertTrue(result['problems'])
        # An unrelated row is kept compressed; only the selected row expands.
        raw = orderedmap_raw(['123', '999'], [zlib.compress(b'first,second,icon\n'), bomb])
        with mock.patch.object(deps, 'LIMIT', 128):
            reader = deps._DefinitionReader({deps.UNIQUE_TABLE: raw})
            row, proof = reader.row(deps.UNIQUE_TABLE, '123')
            self.assertEqual(row, ['first', 'second', 'icon'])
            self.assertEqual(proof['sha256'], hashlib.sha256(raw).hexdigest())
            with self.assertRaisesRegex(ValueError, '解压输出超限'):
                reader.row(deps.UNIQUE_TABLE, '999')

    def test_orderedmap_rejects_bad_offsets_duplicate_keys_and_all_tail_forms(self):
        row = zlib.compress(b'first,second,icon\n')
        bad = [orderedmap_raw(['123'], [row], pairs=[(4, len(row))]),
               orderedmap_raw(['123'], [row], pairs=[(3, len(row)+1)]),
               orderedmap_raw(['123', '456'], [row, row], pairs=[(3, len(row)), (6, len(row)-1)]),
               orderedmap_raw(['123', '123'], [row, row]),
               orderedmap_raw(['123'], [row], index_tail=b'ignored'),
               orderedmap_raw(['123'], [row], row_tail=b'ignored'),
               orderedmap_raw(['123'], [row], compressed_index_tail=b'ignored'),
               orderedmap_raw(['123'], [row+b'ignored']),
               orderedmap_raw(['123'], [row[:-1]])]
        for raw in bad:
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    deps._DefinitionReader({deps.UNIQUE_TABLE: raw}).row(deps.UNIQUE_TABLE, '123')
        raw = orderedmap_raw(['123', '456'], [row, row])
        with mock.patch.object(deps, 'MAX_ITEMS', 1):
            with self.assertRaisesRegex(ValueError, '条目超限'):
                deps._DefinitionReader({deps.UNIQUE_TABLE: raw}).row(deps.UNIQUE_TABLE, '123')

    def test_bomb_ready_effect_slots_and_summon_callback_are_not_lost(self):
        e = lambda name: ['SpecifyEffectDirectly', 'battle/' + name]
        bomb = ['CreateBombMultiball', 0, 'battle/bomb', ['E2', e('ready'), e('near'), e('far')], e('create'), e('destroy'), 'ordinary-text', 0, False]
        result = deps.resolve_command_resources(bomb)
        self.assertFalse(result['problems'])
        self.assertEqual({r['logical'] for r in result['references']}, {'battle/bomb', 'battle/ready', 'battle/near', 'battle/far', 'battle/create', 'battle/destroy'})
        summon = ['CreateSummonsMultiball', 0, 12, [], ['E1', e('ready')], e('create'), e('destroy'), 0, False, 'not-an-asset', 0, 0,
                  ['Command', ['ShowEffect', 0, e('callback')]], {}]
        result = deps.resolve_dsl_resources(['Command', summon])
        self.assertEqual({r['logical'] for r in result['references']}, {'battle/ready', 'battle/create', 'battle/destroy', 'battle/callback'})
        self.assertEqual(result['requiredDefinitions'][0]['key'], 12)
        self.assertTrue(any('12' in p['reason'] and p['domain'] == 'summon' for p in result['problems']))
        self.assertEqual(len(result['handledPointers']), 2)

    def test_funnel_ids_remain_typed_and_known_no_asset_instruction_is_not_unknown(self):
        result = deps.resolve_command_resources(['SpawnFunnel', ['StandardFunnel', 'funnel_fixture'], 0, None, []])
        self.assertFalse(result['references'])
        self.assertEqual(result['requiredDefinitions'][0]['kind'], 'StandardFunnel')
        self.assertTrue(result['problems'][0]['dynamic'])
        result = deps.resolve_command_resources(['SetPowerFilpSuppress', 30])
        self.assertTrue(result['handled'])
        self.assertFalse(result['references'])
        self.assertFalse(result['problems'])
        self.assertTrue(deps.resolve_command_resources(['SetPowerFilpSuppress', []])['problems'])

    def test_retained_draft_if_supplied_does_not_mutate_inputs(self):
        archive = os.environ.get('STUDIO_RETAINED_DRAFT')
        if not archive:
            self.skipTest('set STUDIO_RETAINED_DRAFT to a preserved original project')
        archive = Path(archive)
        raw = archive.read_bytes()
        with zipfile.ZipFile(archive) as source:
            project = json.loads(source.read('project.json'))
            refs = {name: source.read('reference/' + name) for name in project['referenceFiles']}
        before = deps.canonical(project)
        receipt = deps.extract_native_roots(project, refs)
        self.assertEqual(deps.canonical(project), before)
        self.assertEqual(archive.read_bytes(), raw)
        self.assertTrue(receipt['roots'])
        self.assertFalse(receipt['complete'])
        for program in json.loads(refs['data_readable/skill_dependencies.json'])['programs']:
            resolved = deps.resolve_dsl_resources(program['tree'], receipt['element'])
            self.assertFalse(resolved['problems'])
            self.assertTrue(resolved['handledPointers'])


if __name__ == '__main__':
    unittest.main()
