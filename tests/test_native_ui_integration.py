"""Typed UI codecs, graph provenance and negative closure at the public boundary."""
import hashlib
import io
import os
from pathlib import Path
import sys
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from character_dependencies import analyze, resource_catalog
from native_common_dependencies import UI_BRANCHES


def root(logical='scene/test', kind='ui'):
    return {'logical': logical, 'kind': kind, 'domain': 'shared', 'category': 'shared',
            'bucket': 'Common', 'collection': 'test-following-logic', 'layer': 'independent',
            'requester': 'retained-main', 'roles': ['main'], 'forms': ['0'], 'switches': ['base']}


def receipt(logical, raw, kind, context=None, pointer=''):
    proof = {'logical': logical, 'sha256': hashlib.sha256(raw).hexdigest(), 'sourcePointer': '/layouts/0'}
    return {'references': [], 'problems': [], 'texts': [{'name': 'label', 'sourcePointer': '/layouts/0/texts/0'}],
            'sourceIdentity': dict(proof, format=kind), 'sourceProof': {'consumer': 'frozen-test-consumer'},
            'parserCoverage': {'status': 'included', 'fixedReferencesComplete': True},
            'complete': False, 'runtimeAcceptance': False}


class NativeUiGraphIntegrationTests(unittest.TestCase):
    def test_exact_ui_texture_follows_real_atlas_carrier_without_repeating_texture_lookup(self):
        from PIL import Image
        image = io.BytesIO(); Image.new('RGBA', (1, 1), (1, 2, 3, 255)).save(image, format='PNG')
        catalog = resource_catalog({'scene/test.ui.json': b'{}', 'scene/general/sheet.png': image.getvalue(),
            'scene/general/sheet.atlas.json': b'[{"n":"scene/general/cell","x":0,"y":0,"w":1,"h":1}]'})
        def decoder(logical, raw, kind, context=None, pointer=''):
            value = receipt(logical, raw, kind, context)
            value['references'] = [{'logical': 'scene/general/cell', 'kind': 'texture', 'pointer': '/bitmap/path',
                                    'lookup': 'exact-texture', 'origin': 'ui-consumer',
                                    'definitionEvidence': value['sourceIdentity']}]
            return value
        with mock.patch('native_ui_dependencies.resolve_ui_resources', side_effect=decoder):
            result = analyze([root()], catalog)
        self.assertFalse(result['unsupported'])
        self.assertFalse(result['missingReferences'])
        self.assertTrue({'scene/general/cell', 'scene/general/sheet.atlas.json', 'scene/general/sheet.png'} <=
                        {item['logical'] for item in result['dependencies']})
        self.assertFalse(result['unresolvedDynamic'])
        self.assertFalse(result['gameReady'])

    def test_untrusted_selector_metadata_rejected_before_graph_hashing(self):
        for field, value in (('lookup', {}), ('requiredLayouts', [{}]), ('requiredLayouts', 'layout')):
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    analyze([{**root(), field: value}], {})

    def test_ui_codec_not_satisfied_by_same_named_image_or_arbitrary_adapter(self):
        catalog = {'scene/test': {'kind': 'evidence', 'sha256': 'a' * 64}}
        result = analyze([root()], catalog)
        self.assertEqual(result['missingReferences'][0]['logical'], 'scene/test.ui.amf3.deflate')
        self.assertFalse(result['closure']['fullyClosed'])

    def test_compiled_prefix_exact_bytes_and_nested_typed_references_keep_provenance(self):
        inputs = {'compiled/common/scene/test.ui.json': b'{}', 'rich_text/test.html': b'<html><body/></html>'}
        calls = []
        def decoder(logical, raw, kind, context=None, pointer=''):
            calls.append((logical, raw, kind))
            value = receipt(logical, raw, kind, context)
            if kind == 'ui':
                value['references'] = [{'logical': 'rich_text/test', 'kind': 'html', 'pointer': '/known-child',
                                        'definitionEvidence': value['sourceIdentity']}]
            else:
                value['problems'] = [{'pointer': '/body/runtime', 'reason': '运行时内容待核', 'dynamic': True,
                                      'consumerEvidence': {'sha256': 'b' * 64}}]
                value['parserCoverage']['status'] = 'pending'
            return value
        with mock.patch('native_ui_dependencies.resolve_ui_resources', side_effect=decoder):
            result = analyze([root()], resource_catalog(inputs))
        self.assertEqual(calls, [('scene/test.ui.json', b'{}', 'ui'),
                                 ('rich_text/test.html', b'<html><body/></html>', 'html')])
        self.assertEqual(len(result['nativeUiCoverage']), 2)
        self.assertEqual(result['nativeUiCoverage'][0]['entry'], 'scene/test')
        self.assertEqual(result['nativeUiCoverage'][0]['textCount'], 1)
        child = next(item for item in result['dependencies'] if item['logical'] == 'rich_text/test.html')
        self.assertEqual(child['definitionEvidence']['sha256'], hashlib.sha256(b'{}').hexdigest())
        self.assertEqual(child['roles'], ['main'])
        self.assertEqual(result['unresolvedDynamic'][0]['consumerEvidence']['sha256'], 'b' * 64)
        self.assertFalse(result['closure']['fullyClosed'])
        self.assertFalse(result['runtimeAccepted'])

    def test_mixed_ui_read_formats_are_not_silently_selected(self):
        catalog = resource_catalog({'scene/test.ui.json': b'{}', 'scene/test.ui.amf3.deflate': b'other'})
        with mock.patch('native_ui_dependencies.resolve_ui_resources') as decoder:
            result = analyze([root()], catalog)
        decoder.assert_not_called()
        self.assertTrue(any('多个读取格式' in item['reason'] for item in result['unsupported']))
        self.assertFalse(result['closure']['fullyClosed'])

    def test_sticky_platform_identity_conflict_never_reaches_consumer_parser(self):
        inputs = {'compiled/common/scene/test.ui.json': b'{}',
                  'compiled/android/scene/test.ui.json': b'{"different":true}',
                  'compiled/ios/scene/test.ui.json': b'{}'}
        with mock.patch('native_ui_dependencies.resolve_ui_resources') as decoder:
            result = analyze([root()], resource_catalog(inputs))
        decoder.assert_not_called()
        self.assertTrue(any('冲突' in item['reason'] for item in result['unsupported']))

    def test_direct_rich_text_file_image_cannot_be_satisfied_by_atlas_cell(self):
        def decoder(logical, raw, kind, context=None, pointer=''):
            value = receipt(logical, raw, kind, context)
            value['references'] = [{'logical': 'image/known', 'kind': 'texture', 'pointer': '/img/src',
                                    'lookup': 'standalone-file-texture', 'origin': 'html-consumer',
                                    'definitionEvidence': value['sourceIdentity']}]
            return value
        catalog = resource_catalog({'rich_text/test.html': b'<html/>'})
        catalog['image/known'] = {'kind': 'atlas-cell', 'sha256': 'a' * 64}
        with mock.patch('native_ui_dependencies.resolve_ui_resources', side_effect=decoder):
            result = analyze([root('rich_text/test', 'html')], catalog)
        missing = next(item for item in result['missingReferences'] if item['logical'] == 'image/known.png')
        self.assertEqual(missing['definitionEvidence']['logical'], 'rich_text/test.html')
        self.assertFalse(result['closure']['fullyClosed'])

    def test_missing_button_layout_is_not_hidden_by_same_file_earlier_visit(self):
        def decoder(logical, raw, kind, context=None, pointer=''):
            value = receipt(logical, raw, kind, context)
            if kind == 'html':
                value['references'] = [{'logical': 'scene/button', 'kind': 'ui', 'pointer': '/button/base',
                                        'requiredLayouts': [name]} for name in ('present', 'missing')]
            else:
                value['layoutIds'] = ['present']
            return value
        catalog = resource_catalog({'rich_text/test.html': b'<html/>', 'scene/button.ui.json': b'{}'})
        with mock.patch('native_ui_dependencies.resolve_ui_resources', side_effect=decoder):
            result = analyze([root('rich_text/test', 'html')], catalog)
        self.assertTrue(any(item.get('requiredLayout') == 'missing' for item in result['unsupported']))
        self.assertFalse(result['closure']['fullyClosed'])

    def test_real_twelve_entries_are_read_from_frozen_reference_without_runtime_admission(self):
        path = Path(os.environ.get('STUDIO_NATIVE_COMPLEX_REFERENCE', 'missing-reference'))
        if not path.is_file():
            self.skipTest('Frozen current-native UI reference unavailable')
        with zipfile.ZipFile(path) as archive:
            files = {name: archive.read(name) for name in archive.namelist() if not name.endswith('/')}
        if 'scene/battle/pause_menu.ui.amf3.deflate' not in files:
            self.skipTest('Reference predates the twelve UI inputs')
        roots = [root(logical, 'html' if logical.startswith('rich_text/') else 'ui')
                 for branch in UI_BRANCHES for logical in branch[-1]]
        result = analyze(roots, resource_catalog(files), reference_files=files)
        expected = {item['logical'] for item in roots}
        seen = {item['entry'] for item in result['nativeUiCoverage']}
        self.assertTrue(expected.issubset(seen), expected - seen)
        for item in result['nativeUiCoverage']:
            self.assertEqual(item['sha256'], hashlib.sha256(files[item['logical']]).hexdigest())
        self.assertTrue(result['unresolvedDynamic'])
        self.assertFalse(result['unsupported'])
        self.assertFalse(result['closure']['fullyClosed'])
        self.assertFalse(result['gameReady'])


if __name__ == '__main__':
    unittest.main()
