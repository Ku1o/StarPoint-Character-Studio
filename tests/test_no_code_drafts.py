"""Editable drafts retain unsafe-for-client rows without weakening transport safety."""
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio_core import ProjectStore, StudioError, fresh_project, project_checks, validate, validate_draft
from studio_compile import compile_project
from project_storage import copy_project
import native_gameplay as native
from test_native_gameplay import pack


class NoCodeDraftTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = ProjectStore(Path(self.tmp.name) / 'projects')

    def native_project(self):
        definitions = pack()
        class Library:
            def load(self):
                return definitions
        p = self.store.create('有待核技术行的创作草稿')
        return native.attach(self.store, p['id'], p['revision'], Library(), '10')

    def test_new_code_is_automatic_stable_and_empty_legacy_code_roundtrips(self):
        p = self.store.create('只写中文和意图')
        code = p['identity']['code']
        self.assertEqual(code, 'character_' + p['id'])
        self.assertRegex(code, r'^[a-z][a-z0-9_]{1,70}$')
        self.assertNotEqual(fresh_project()['identity']['code'], code)
        p['identity']['code'] = ''
        p['productionBrief']['plans']['activeSkill']['authorDescription'] = '攻击后给队友回复，数值需要讨论。'
        p = self.store.save(p)
        imported = self.store.import_archive(self.store.export(p['id']))
        self.assertEqual(imported['identity']['code'], '')
        self.assertEqual(imported['productionBrief'], p['productionBrief'])
        self.assertTrue(any(i['code'] == 'resource_code_pending' for i in project_checks(p)['issues'] if 'code' in i))
        with self.assertRaises(StudioError):
            compile_project(self.store, p['id'])

    def test_invalid_ability_rows_survive_edit_export_import_and_migration(self):
        p = self.native_project()
        blocks = native.describe.layout('ability')['blocks']
        row = p['nativeGameplay']['abilities'][0]['rows'][0]
        row[1] = ''  # Bool cannot reach the client, but is still bounded draft text.
        row[6] = ''
        row[blocks['instant_precontent']] = ''
        p['nativeGameplay']['futureField'] = {'keep': '原始记录'}
        before = copy.deepcopy(p['nativeGameplay'])
        p['productionBrief']['notes'] = '保留旧行，作者不会代码，请制作方核对。'
        p = self.store.save(p)
        self.assertEqual(p['nativeGameplay'], before)
        self.assertTrue(validate_draft(copy.deepcopy(p)))
        issues = project_checks(p)['issues']
        self.assertTrue(any(i.get('code') == 'native_row_not_ready' and i['owner'] == 'maker' for i in issues))
        self.assertTrue(native.describe_native(before)['installed'])
        with self.assertRaises(ValueError):
            validate(copy.deepcopy(p))
        with self.assertRaises(ValueError):
            native.compile_native(before)
        with self.assertRaises(ValueError):
            compile_project(self.store, p['id'])
        with self.assertRaises(ValueError):
            native.edit(self.store, p['id'], p['revision'], 'patch', 1, 0, {'value': 20})
        exported = self.store.export(p['id'])
        imported = self.store.import_archive(exported)
        self.assertEqual(imported['nativeGameplay'], before)
        self.assertEqual(imported['productionBrief'], p['productionBrief'])
        other = ProjectStore(Path(self.tmp.name) / 'migrated')
        migrated = copy_project(other, self.store.directory(p['id']), p)
        # copy_project returns its migration receipt rather than a project.
        migrated_p = other.load(migrated['id'])
        self.assertEqual(migrated_p['nativeGameplay'], before)
        self.assertEqual(self.store.load(p['id'])['nativeGameplay'], before)

    def test_unchanged_invalid_source_rows_are_not_compilable(self):
        p = self.native_project()
        n = p['nativeGameplay']
        source_row = n['source']['data']['character']['records']['abilities']['selected']['81']['rows'][0]
        source_row[6] = ''
        n['abilities'][0]['rows'][0] = copy.deepcopy(source_row)
        n['source']['sha256'] = native.digest(n['source']['data'])
        native.validate_native(n, draft=True)
        self.assertTrue(native.native_readiness_issues(n))
        with self.assertRaises(ValueError):
            native.validate_native(n)

    def test_source_hash_and_transport_errors_still_reject_without_overwrite(self):
        p = self.native_project()
        bad = copy.deepcopy(p)
        bad['nativeGameplay']['source']['data']['version'] = 'changed-without-identity'
        with self.assertRaises(ValueError):
            validate_draft(bad)
        # The ordinary save API also retains the previous source identity.
        p = self.store.save(bad)
        self.assertEqual(p['nativeGameplay']['source']['data']['version'], '1.4.54')
        baseline = self.store.directory(p['id']).joinpath('project.json').read_bytes()
        for code in ('../outside', 'a/b', r'a\b', 'C:outside', '.', '..', 'a\x00b'):
            bad = copy.deepcopy(p)
            bad['identity']['code'] = code
            with self.subTest(code=code), self.assertRaises(ValueError):
                self.store.save(bad)
        bad = copy.deepcopy(p)
        bad['formatVersion'] = 2
        with self.assertRaises(ValueError):
            self.store.save(bad)
        bad = copy.deepcopy(p)
        bad['animations'][0]['clips'] = [{'asset': 'absent', 'hold': 1}]
        with self.assertRaises(ValueError):
            self.store.save(bad)
        self.assertEqual(self.store.directory(p['id']).joinpath('project.json').read_bytes(), baseline)

    def test_original_source_identity_is_still_immutable(self):
        p = self.store.create('原稿身份')
        from source_intake import register_package
        register_package(p, '原稿尚未取得.zip')
        self.store._write(p)
        bad = copy.deepcopy(p)
        bad['sourceIntake']['packages'] = []
        with self.assertRaises(ValueError):
            self.store.save(bad)
        self.assertEqual(self.store.load(p['id'])['sourceIntake'], p['sourceIntake'])

    def test_retained_problem_project_preserves_original_rows_and_payloads(self):
        selected = os.environ.get('STUDIO_RETAINED_DRAFT')
        if not selected:
            self.skipTest('Set STUDIO_RETAINED_DRAFT for retained author-project acceptance')
        source = Path(selected)
        raw = source.read_bytes()
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            files = {name: z.read(name) for name in z.namelist() if not name.endswith('/')}
        json_name = next(name for name in files if Path(name).name == 'project.json')
        original = json.loads(files[json_name])
        self.assertTrue(original.get('nativeGameplay'), 'Fixture must contain original native rows')
        p = self.store.import_archive(raw, source.name)
        self.assertEqual(p['nativeGameplay'], original['nativeGameplay'])
        self.assertTrue(native.native_readiness_issues(p['nativeGameplay']))
        p['productionBrief']['notes'] = '角色原稿保留；技术行未知，请制作方核对，作者只补创作说明。'
        p = self.store.save(p)
        with self.assertRaises(ValueError):
            compile_project(self.store, p['id'])
        exported = self.store.export(p['id'])
        restored = self.store.import_archive(exported)
        self.assertEqual(restored['nativeGameplay'], original['nativeGameplay'])
        self.assertEqual(restored['productionBrief'], p['productionBrief'])
        prefix = json_name.removesuffix('project.json')
        with zipfile.ZipFile(io.BytesIO(exported)) as z:
            for path, payload in files.items():
                relative = path.removeprefix(prefix)
                if relative.startswith(('assets/', 'reference/', 'sources/')):
                    self.assertEqual(z.read(relative), payload, relative)
        self.assertEqual(source.read_bytes(), raw)


if __name__ == '__main__':
    unittest.main()
