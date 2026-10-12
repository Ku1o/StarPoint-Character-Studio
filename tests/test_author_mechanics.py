"""Structured maker plans preserve original author requirements and data."""
import copy
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import author_mechanics
import author_gameplay_complex
from dependency_assistance import build as assistance


def pending(details, plan='ability0'):
    card = {'text': '保留的原想法', 'details': details}
    return {'id': 'card-1', 'plan': plan, 'planLabel': '能力1', 'card': card, 'state': 'pending',
            'detailPrompts': author_gameplay_complex.assistance_prompts(plan, card)}


class AuthorMechanicsTests(unittest.TestCase):
    def test_summon_details_and_unknown_requirements_are_preserved_without_inventing_assets(self):
        details = {'mechanic': 'summon', 'count': '两只', 'lifetime': '10秒',
                   'reference': '已有凉月动作', 'unknown': '跨阶段不要消失'}
        cards = [pending(details)]
        project = {'id': 'p', 'revision': 1, 'nativeGameplay': {'unchanged': True}}
        before = copy.deepcopy((project, cards))
        report = author_mechanics.build(project, cards)
        self.assertEqual((project, cards), before)
        plan = report['plans'][0]
        provided = {row['field']: row['value'] for row in plan['providedDetails']}
        self.assertEqual(provided['count'], '两只')
        self.assertEqual(provided['unknown'], details['unknown'])
        self.assertNotIn('count', {row['field'] for row in plan['missingDetails']})
        self.assertEqual(plan['referenceCheck']['status'], 'text_only')
        self.assertTrue(all(step['status'] == 'pending' and step['owner'] == 'maker' for step in plan['makerSteps']))
        self.assertFalse(plan['canAutoApply'])
        self.assertFalse(plan['behaviorVerified'])

    def test_special_recovery_and_free_text_survive_and_do_not_mark_behavior_verified(self):
        card = pending({'mechanic': 'special', 'recovery': '被打断时回到原姿势'})
        free = [{'plan': 'activeSkill', 'planLabel': '主动技能', 'text': '原手填：动画不可改。'}]
        report = author_mechanics.build({'id': 'p', 'revision': 1}, [card], free)
        self.assertEqual(report['plans'][0]['mechanic'], 'special')
        self.assertEqual(report['plans'][0]['providedDetails'][0]['value'], '被打断时回到原姿势')
        self.assertEqual(report['freeRequirements'][0]['text'], free[0]['text'])
        self.assertFalse(report['gameReady'])
        old = report['token']
        self.assertNotEqual(old, author_mechanics.build({'id': 'p', 'revision': 2}, [card], free)['token'])

    def test_explicit_reference_inspection_is_cached_and_retain_unknown_or_changed_evidence(self):
        details = {'mechanic': 'skill_reuse', 'referenceChoice': 'chosen', 'referenceDigest': 'a' * 64}
        first = pending(details)
        second = {**copy.deepcopy(first), 'id': 'card-2'}
        checked = {'status': 'pending', 'label': '原参考已变更', 'evidence': [{'reason': 'hash mismatch'}],
                   'behaviorVerified': False, 'gameReady': False}
        with mock.patch('author_reuse.inspect', return_value=checked) as inspect:
            result = author_mechanics.build({'id': 'p'}, [first, second], store=object())
        self.assertEqual(inspect.call_count, 1)
        self.assertEqual(result['plans'][1]['referenceCheck'], checked)
        self.assertFalse(result['plans'][0]['canAutoApply'])

    def test_filled_summon_information_goes_to_provided_section_not_repeated_questions(self):
        card = pending({'mechanic': 'summon', 'reference': '原动作', 'appearance': '沿用原图',
                        'count': '两只', 'lifetime': '10秒', 'behavior': '跟随并攻击', 'sequence': '先出现后攻击'})
        plans = author_mechanics.build({'id': 'p'}, [card])
        result = assistance({'id': 'p'}, gameplay={'integrationPlans': plans,
            'items': [{'id': 'card-1', 'status': 'pending', 'planLabel': '能力1', 'text': '保留的原想法'}]})
        request = result['requests'][0]
        self.assertEqual(len(request['providedDetails']), 6)
        self.assertFalse(request['missingDetails'])
        self.assertIn('已说明', request['authorInput'])
        self.assertNotIn('可以补充或请协助', request['authorInput'])
        self.assertIn('召唤行为', request['makerAction'])
        self.assertFalse(request['integrationVerified'])

    def test_persisted_reference_without_valid_digest_never_gets_checked(self):
        for digest in (None, '', 'bad', 'x' * 64, {}):
            with self.subTest(digest=digest):
                details = {'mechanic': 'skill_reuse', 'referenceChoice': 'chosen', 'referenceDigest': digest}
                with mock.patch('author_reuse.inspect') as inspect:
                    result = author_mechanics.build({'id': 'p'}, [pending(details)], store=object())
                self.assertFalse(inspect.called)
                self.assertEqual(result['plans'][0]['referenceCheck']['status'], 'pending')
                self.assertFalse(result['gameReady'])

    def test_malformed_or_unknown_details_stay_pending_and_basic_supported_cards_are_not_planned(self):
        cards = [pending({'mechanic': [], 'reference': {'bad': True}}), pending({'mechanic': 'future', 'unknown': '原需求'})]
        cards.append({'state': 'supported'})
        result = author_mechanics.build({'id': 'p'}, cards)
        self.assertEqual(result['planCount'], 2)
        self.assertTrue(all(plan['mechanic'] == 'custom' for plan in result['plans']))


if __name__ == '__main__': unittest.main()
