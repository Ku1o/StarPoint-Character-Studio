"""Game UI diagnostics must not hide an author's character resource gaps."""
import copy
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from character_dependencies import analyze, resource_catalog, validate
from dependency_assistance import build
from native_common_dependencies import UI_BRANCHES, conditional_common_resources


TECHNICAL_OWNER = 'game-common-ui'
GAP_KEYS = ('missingReferences', 'unresolvedDynamic', 'unsupported')


def root(logical='scene/example', domain='shared', kind='ui', **metadata):
    return {'logical': logical, 'kind': kind, 'domain': domain, 'category': domain,
            'bucket': 'Common', 'collection': 'same-collection', 'layer': 'independent',
            'requester': 'same-requester', 'source': 'frozen/source',
            'roles': ['main'], 'forms': ['0'], 'switches': ['base'], **metadata}


def ui_receipt(logical, raw, kind, context=None, pointer=''):
    evidence = {'logical': logical, 'sha256': 'a' * 64,
                'sourcePointer': '/layouts/0/children/bitmaps/0/attributes/path'}
    return {'references': [{'logical': 'character/example/ui/missing', 'kind': 'texture',
                            'origin': 'ui-consumer', 'lookup': 'exact-texture',
                            'pointer': evidence['sourcePointer'], 'definitionEvidence': evidence}],
            'problems': [{'pointer': '/text', 'reason': 'runtime binding pending', 'dynamic': True},
                         {'pointer': '/unsupported', 'reason': 'unsupported consumer', 'dynamic': False}],
            'texts': [], 'sourceIdentity': {'format': 'ui'}, 'sourceProof': {},
            'parserCoverage': {'status': 'pending', 'fixedReferencesComplete': False}}


def gap_closure(report):
    return {key: report[key] for key in GAP_KEYS}


class DependencyOwnerScopeTests(unittest.TestCase):
    def test_game_ui_gaps_keep_full_technical_evidence_without_author_requests(self):
        catalog = resource_catalog({'scene/example.ui.json': b'{}'})
        with mock.patch('native_ui_dependencies.resolve_ui_resources', side_effect=ui_receipt):
            report = analyze([root(resourceOwner=TECHNICAL_OWNER)], catalog)
        self.assertEqual(report['counts']['missing'], 1)
        self.assertEqual(report['counts']['dynamic'], 1)
        self.assertEqual(report['counts']['unsupported'], 1)
        self.assertEqual(report['authorCounts'], {'resolved': 0, 'missing': 0, 'dynamic': 0, 'unsupported': 0})
        closure = gap_closure(report)
        before = copy.deepcopy(closure)
        assistance = build({'id': 'p', 'revision': 1}, closure)
        self.assertEqual(closure, before)
        self.assertFalse(assistance['requests'])
        self.assertEqual(assistance['requestCount'], 0)
        self.assertEqual(len(assistance['technicalRequests']), 1)
        technical = assistance['technicalRequests'][0]
        self.assertFalse(technical['authorInputRequired'])
        expected = [{'kind': key, **item} for key in GAP_KEYS for item in report[key]]
        self.assertEqual(technical['evidence'], expected)
        missing = next(item for item in technical['evidence'] if item['kind'] == 'missingReferences')
        self.assertEqual(missing['definitionEvidence']['sourcePointer'], ui_receipt('', b'', '')['references'][0]['pointer'])
        self.assertFalse(report['gameReady'])
        self.assertFalse(report['closure']['fullyClosed'])

    def test_same_ui_and_missing_child_are_traversed_for_both_owners_in_either_order(self):
        for owners in ((TECHNICAL_OWNER, 'character'), ('character', TECHNICAL_OWNER)):
            with self.subTest(owners=owners):
                catalog = resource_catalog({'scene/example.ui.json': b'{}'})
                with mock.patch('native_ui_dependencies.resolve_ui_resources', side_effect=ui_receipt) as decoder:
                    report = analyze([root(resourceOwner=owner) for owner in owners], catalog)
                self.assertEqual(decoder.call_count, 2)
                for key in GAP_KEYS:
                    self.assertEqual(len(report[key]), 2)
                    self.assertEqual({item['resourceOwner'] for item in report[key]}, set(owners))
                self.assertEqual(report['authorCounts'], {'resolved': 1, 'missing': 1, 'dynamic': 1, 'unsupported': 1})
                self.assertEqual(len(report['dependencies']), 1)
                self.assertEqual({item['resourceOwner'] for item in report['dependencies'][0]['contexts']}, set(owners))
                assistance = build({'id': 'p'}, gap_closure(report))
                author_evidence = [item for request in assistance['requests'] for item in request['evidence']]
                technical_evidence = assistance['technicalRequests'][0]['evidence']
                self.assertEqual(len(author_evidence), 3)
                self.assertEqual(len(technical_evidence), 3)
                self.assertTrue(all(item['resourceOwner'] == 'character' for item in author_evidence))
                self.assertTrue(all(item['resourceOwner'] == TECHNICAL_OWNER for item in technical_evidence))

    def test_ui_origin_shared_domain_and_character_paths_do_not_imply_technical_ownership(self):
        roots = [root('character/example/ui/portrait', 'ui', 'texture', origin='ui-consumer'),
                 root('character/example/pixelart/special', 'special', 'effect'),
                 root('character/example/summon/body', 'summon', 'effect'),
                 root('battle/common/custom_hit', 'shared', 'texture', origin='ui-consumer')]
        report = analyze(roots, {})
        self.assertEqual(report['authorCounts']['missing'], 4)
        self.assertEqual(len(report['missingReferences']), 4)
        assistance = build({'id': 'p'}, gap_closure(report))
        self.assertEqual({request['domain'] for request in assistance['requests']}, {'ui', 'special', 'summon', 'shared'})
        self.assertFalse(assistance['technicalRequests'])
        self.assertTrue(all('resourceOwner' not in item for item in report['missingReferences']))

    def test_non_string_owner_is_rejected_by_public_validation(self):
        for value in ({}, [], 1, None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate({'dependencyScope': {'roots': [root(resourceOwner=value)]}})

    def test_only_the_twelve_common_ui_html_collector_roots_receive_marker(self):
        receipt = conditional_common_resources()
        expected = {logical for branch in UI_BRANCHES for logical in branch[-1]}
        self.assertEqual(len(expected), 12)
        marked = [item for item in receipt['references'] if item['context'].get('resourceOwner') == TECHNICAL_OWNER]
        self.assertEqual({item['logical'] for item in marked}, expected)
        self.assertEqual(len(marked), 12)
        self.assertTrue(all(item['context']['kind'] in ('ui', 'html') for item in marked))
        for item in receipt['references']:
            if item['logical'] not in expected:
                self.assertNotEqual(item['context'].get('resourceOwner'), TECHNICAL_OWNER)


if __name__ == '__main__':
    unittest.main()
