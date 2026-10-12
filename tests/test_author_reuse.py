"""Single-reference checks must preserve draft bytes and all author intent."""
import copy
import hashlib
import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import author_reuse as reuse
import native_gameplay
from character_dependencies import canonical
from studio_core import ProjectStore, amf_bytes
from test_native_gameplay import pack
from test_native_summon_dependencies import flat, multiball, summon_command
import native_summon_dependencies as summons


class AuthorReuseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = ProjectStore(Path(self.tmp.name) / 'projects')
        self.project = self.store.create('单项复用')
        self.definition = pack()
        class Library:
            def load(inner):
                return self.definition
        self.project = native_gameplay.attach(self.store, self.project['id'], 0, Library(), '10')

    def references(self, files):
        root = self.store.directory(self.project['id']) / 'reference'
        for name, raw in files.items():
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        self.project['referenceFiles'] = list(files)

    def option(self, kind='skill'):
        return next(item for item in reuse.catalog(self.store, self.project)['options'] if item['kind'] == kind)

    def test_exact_skill_readable_mapping_is_read_only_and_not_runtime_verified(self):
        self.references({'data_readable/skill_dependencies.json': canonical({'programs': [{'logical': 'fixture_1', 'tree': ['Block', []]}]})})
        before = copy.deepcopy(self.project)
        disk = self.store.load(self.project['id'])
        selected = self.option()
        self.assertNotIn('inputs', selected['identity'])
        self.assertEqual(selected['identity']['inputCount'], 1)
        result = reuse.inspect(self.store, self.project, selected['id'], selected['identity']['sha256'])
        self.assertEqual(result['status'], 'references_checked')
        self.assertFalse(result['behaviorVerified']); self.assertFalse(result['gameReady'])
        self.assertEqual(before, self.project); self.assertEqual(disk, self.store.load(self.project['id']))
        self.assertEqual(result['evidence'][0]['logical'], 'fixture_1.action.dsl.amf3.deflate')

    def test_draft_illegal_original_ability_does_not_block_reference(self):
        original = self.definition['characters']['10']['records']['abilities']['selected']['81']['rows'][0]
        original[6] = ''
        native = self.project['nativeGameplay']
        native['source']['data']['character']['records']['abilities']['selected']['81']['rows'][0][6] = ''
        native['source']['sha256'] = native_gameplay.digest(native['source']['data'])
        native['abilities'][0]['rows'][0][6] = ''
        before = copy.deepcopy(native)
        self.assertTrue(self.option())
        self.assertEqual(before, native)

    def test_changed_bytes_or_object_invalidates_exact_choice(self):
        name = 'fixture_1.action.dsl.amf3.deflate'
        self.references({name: amf_bytes(['Block', []])})
        selected = self.option()
        (self.store.directory(self.project['id']) / 'reference' / name).write_bytes(amf_bytes(['Block', [['Command', ['Trace', 'changed']]]]))
        result = reuse.inspect(self.store, self.project, selected['id'], selected['identity']['sha256'])
        self.assertEqual(result['status'], 'pending'); self.assertIn('身份已变化', result['unsupported'][0]['reason'])
        self.project['nativeGameplay']['skills'][0]['fields'][0] = '新技能'
        self.assertEqual(reuse.inspect(self.store, self.project, selected['id'])['status'], 'pending')

    def test_missing_decode_and_conflicting_program_are_pending(self):
        selected = self.option()
        self.assertTrue(reuse.inspect(self.store, self.project, selected['id'])['missing'])
        self.references({'fixture_1.action.dsl.amf3.deflate': b'bad',
                         'data_readable/skill_dependencies.json': canonical({'programs': [{'logical': 'fixture_1', 'tree': ['Block', []]}]})})
        selected = self.option()
        result = reuse.inspect(self.store, self.project, selected['id'])
        self.assertEqual(result['status'], 'pending'); self.assertTrue(result['unsupported'])

    def test_no_name_guess_and_no_common_scene_roots(self):
        self.references({'fixture_1.action.dsl.amf3.deflate': amf_bytes(['Block', []]),
                         'battle/common/unused.timeline.json': canonical({'sounds': [{'path': 'sound_effect/unrelated'}]})})
        selected = self.option()
        result = reuse.inspect(self.store, self.project, selected['id'])
        self.assertEqual(result['status'], 'references_checked')
        self.assertEqual(result['counts']['resolved'], 1)
        self.assertEqual(reuse.inspect(self.store, self.project, '测试技能')['status'], 'pending')

    def test_bounded_declared_paths_and_duplicates(self):
        self.project['referenceFiles'] = ['../outside', 'ok.json', 'ok.json']
        root = self.store.directory(self.project['id']) / 'reference'; root.mkdir(exist_ok=True)
        (root / 'ok.json').write_bytes(b'{}')
        result = reuse.catalog(self.store, self.project)
        self.assertEqual(len(result['issues']), 2)
        selected = next(item for item in result['options'] if item['kind'] == 'skill')
        self.assertEqual(reuse.inspect(self.store, self.project, selected['id'])['status'], 'pending')
        with mock.patch.object(reuse, 'MAX_BYTES', 1):
            self.assertTrue(reuse.catalog(self.store, self.project)['issues'])

    def test_resolved_reference_escape_is_rejected(self):
        root = self.store.directory(self.project['id'])
        outside = Path(self.tmp.name) / 'outside'; outside.mkdir()
        self.project['referenceFiles'] = ['file.json']
        original = Path.resolve
        def resolve(path, *args, **kwargs):
            if path == root / 'reference':
                return outside
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, 'resolve', resolve):
            result = reuse.catalog(self.store, self.project)
        self.assertTrue(any('越出' in item['reason'] for item in result['issues']))

    def test_asset_original_bytes_and_hash_mismatch(self):
        image = Image.new('RGBA', (2, 2)); out = io.BytesIO(); image.save(out, 'PNG')
        raw = out.getvalue(); name = 'pixel.png'
        asset_root = self.store.directory(self.project['id']) / 'assets'; asset_root.mkdir(exist_ok=True)
        (asset_root / name).write_bytes(raw)
        self.project['assets'] = {'a': {'file': name, 'sha256': hashlib.sha256(raw).hexdigest()}}
        self.project['animations'] = [{'id': 'a1', 'name': '已有动作', 'clips': [{'asset': 'a', 'hold': 1}]}]
        selected = self.option('animation')
        self.assertEqual(reuse.inspect(self.store, self.project, selected['id'])['status'], 'references_checked')
        self.project['assets']['a']['sha256'] = '0' * 64
        self.assertEqual(reuse.inspect(self.store, self.project, selected['id'])['status'], 'pending')
        self.project['animations'].append(copy.deepcopy(self.project['animations'][0]))
        self.assertFalse(any(item['kind'] == 'animation' for item in reuse.catalog(self.store, self.project)['options']))

    def test_real_type_command_extracts_summon_choice_and_reads_definition(self):
        fields = multiball(); fields[9] = '(None)'; fields[20:24] = ['(None)'] * 4
        self.references({'fixture_1.action.dsl.amf3.deflate': amf_bytes(['Block', [['Command', summon_command(7)]]]),
                         summons.MULTIBALL_TABLES[0]: flat({}), summons.MULTIBALL_TABLES[1]: flat({'7': fields})})
        selected = self.option('summon')
        self.assertNotIn('Multiball', selected['label'])
        self.assertNotIn(' 7', selected['label'])
        result = reuse.inspect(self.store, self.project, selected['id'])
        self.assertEqual(result['status'], 'pending')
        self.assertTrue(any('character/summon_body/pixelart/pixelart' == item.get('logical') for item in result['missing']))
        self.assertTrue(any(item.get('definition', {}).get('kind') == 'Multiball' for item in result['evidence']) or result['evidence'][0]['definitions'])

    def test_no_summon_is_invented_when_program_does_not_summon(self):
        self.references({'fixture_1.action.dsl.amf3.deflate': amf_bytes(['Block', []])})
        self.assertFalse(any(item['kind'] == 'summon' for item in reuse.catalog(self.store, self.project)['options']))

    def test_compiled_alias_conflicts_are_not_silently_selected(self):
        name = 'fixture_1.action.dsl.amf3.deflate'
        self.references({name: amf_bytes(['Block', []]),
                         'compiled/android/' + name: amf_bytes(['Block', [['Command', ['Trace', 'different']]]])})
        selected = self.option()
        result = reuse.inspect(self.store, self.project, selected['id'])
        self.assertEqual(result['status'], 'pending'); self.assertTrue(result['unsupported'])

    def test_one_oversized_object_does_not_hide_other_choices(self):
        nested = {}
        for _ in range(130):
            nested = {'child': nested}
        self.project['animations'] = [{'id': 'deep', 'name': '过深动作', 'extra': nested},
                                      {'id': 'safe', 'name': '正常空槽', 'clips': []}]
        result = reuse.catalog(self.store, self.project)
        self.assertEqual(len([item for item in result['options'] if item['kind'] == 'animation']), 2)
        selected = next(item for item in result['options'] if '过深动作' in item['label'])
        self.assertTrue(reuse.inspect(self.store, self.project, selected['id'])['unsupported'])

    def test_real_retained_1110022_optional_explicit_archive(self):
        path = os.environ.get('STUDIO_NATIVE_COMPLEX_REFERENCE')
        if not path:
            self.skipTest('explicit frozen technical archive required')
        with zipfile.ZipFile(path) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        # An independent fixture verifies lookup, never changes either author's
        # preserved program or implies their programs summon this entity.
        files['fixture_1.action.dsl.amf3.deflate'] = amf_bytes(['Block', [['Command', summon_command(1110022)]]])
        self.references(files)
        selected = self.option('summon')
        result = reuse.inspect(self.store, self.project, selected['id'])
        # Fixture command uses three unprovided ready/create/destroy effects.
        # Keep these honest gaps while checking the independently real body.
        self.assertEqual(result['status'], 'pending')
        self.assertEqual({item['logical'] for item in result['missing']}, {'battle/ready', 'battle/create', 'battle/destroy'})
        self.assertFalse(result['dynamic']); self.assertFalse(result['unsupported'])
        self.assertFalse(result['gameReady']); self.assertFalse(result['behaviorVerified'])
        self.assertTrue(any(item.get('logical') == 'character/pirates/pixelart/pixelart' for item in result['evidence']))
        definitions = result['evidence'][0]['definitions']
        self.assertEqual([item['key'] for item in definitions if item['kind'] == 'Ability'], ['90002', '90003'])


if __name__ == '__main__':
    unittest.main()
