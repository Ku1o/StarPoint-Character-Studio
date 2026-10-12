"""Portable maker progress stays separate from original work and game checks."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import author_gameplay
import mechanics_todo as todo
import native_gameplay as native
from studio_core import ProjectStore, archive_files, make_zip
from test_native_gameplay import pack


def complex_card(mechanic, text, **details):
    return {'trigger': 'skill', 'target': 'self', 'effect': 'custom',
            'amount': '', 'duration': '', 'stacking': 'unmarked', 'text': text,
            'details': {'mechanic': mechanic, **details}}


class MechanicsTodoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = ProjectStore(Path(self.tmp.name) / 'projects')
        self.project = self.store.create('制作待办')
        definition = pack()
        class Library:
            def load(inner):
                return definition
        self.project = native.attach(self.store, self.project['id'], 0, Library(), '10')
        self.project['notes'] = '原填写说明：原动画和DSL完整保留。'
        plans = self.project['productionBrief']['plans']
        plans['abilities'][0]['authorCards'] = [complex_card('summon', '召唤两只跟随物', count='两只',
                                                           unknown='跨阶段保留原状态')]
        plans['activeSkill']['authorCards'] = [complex_card('special', '进入特殊形态并恢复原姿势',
                                                           recovery='中断时恢复原姿势')]
        self.project = self.store.save(self.project)

    def current(self):
        self.project = self.store.load(self.project['id'])
        return todo.report(self.store, self.project)

    def change(self, plan_index=0, step_index=0, state='in_progress', note='已核对动作和来源'):
        report = self.current()
        plan = report['plans'][plan_index]
        self.project = todo.update(self.store, self.project['id'], self.project['revision'], report['token'],
                                   plan['cardId'], plan['makerSteps'][step_index]['id'], state, note)
        return report

    def test_multistep_cross_card_append_only_save_and_no_game_acceptance(self):
        before = copy.deepcopy(self.project)
        original = self.current()
        self.assertGreaterEqual(len(original['plans']), 2)
        self.change(0, 0, 'in_progress', '已准备进入和退出动作')
        self.change(0, 1, 'needs_help', '需要协助核对打断恢复')
        self.change(1, 0, 'ready_for_review', '已准备召唤定义，等待实际运行核验')
        self.change(0, 0, 'ready_for_review', '已补充动作路径与中断说明')
        after = self.current()
        self.assertEqual(len(after['workflowHistory']), 4)
        self.assertEqual(after['workflowHistory'][0]['state'], 'in_progress')
        self.assertEqual(after['plans'][0]['makerSteps'][0]['historyCount'], 2)
        self.assertEqual(after['plans'][0]['makerSteps'][1]['workflowState'], 'needs_help')
        self.assertEqual(after['plans'][1]['makerSteps'][0]['workflowState'], 'ready_for_review')
        for plan in after['plans']:
            self.assertFalse(plan['gameReady'])
            self.assertFalse(plan['behaviorVerified'])
            for step in plan['makerSteps']:
                self.assertEqual(step['status'], 'pending')
                self.assertFalse(step['gameReady'])
                self.assertFalse(step['behaviorVerified'])
        clean = copy.deepcopy(self.project)
        for key in ('mechanicsTodo', 'revision', 'updated'):
            clean.pop(key, None)
        for key in ('revision', 'updated'):
            before.pop(key, None)
        self.assertEqual(clean, before)

    def test_merge_is_readonly_idempotent_and_uses_same_report_token(self):
        self.change()
        raw = author_gameplay.preview(self.project, store=self.store)['integrationPlans']
        before = copy.deepcopy((raw, self.project))
        merged = todo.merge(raw, self.project)
        self.assertEqual((raw, self.project), before)
        self.assertEqual(todo.merge(merged, self.project), merged)
        with mock.patch('author_gameplay.preview', side_effect=AssertionError('must reuse complete plans')):
            report = todo.report(self.store, self.project, merged)
        self.assertEqual(report['token'], merged['todoToken'])
        self.assertEqual(merged['token'], raw['token'])
        self.assertEqual(report['planToken'], raw['token'])
        self.assertEqual(report['todoStates']['ready_for_review'], '准备好待验')

    def test_stale_revision_token_and_unknown_card_or_step_never_save(self):
        report = self.current()
        plan = report['plans'][0]
        args = [self.store, self.project['id'], self.project['revision'], report['token'],
                plan['cardId'], plan['makerSteps'][0]['id'], 'in_progress', '原说明']
        with mock.patch.object(self.store, 'save', wraps=self.store.save) as save:
            for position, value in ((2, self.project['revision'] - 1), (2, True), (3, 'a' * 64),
                                    (4, 'unknown-card'), (5, 'unknown-step'),
                                    (6, 'complete'), (7, {'unsafe': True})):
                altered = list(args)
                altered[position] = value
                with self.subTest(position=position, value=value), self.assertRaises(ValueError):
                    todo.update(*altered)
            self.assertFalse(save.called)
        self.change()
        with self.assertRaisesRegex(ValueError, '工程已更新'):
            todo.update(*args)

    def test_ready_for_review_requires_explanation(self):
        before = copy.deepcopy(self.project)
        for note in ('', ' \n\t', '\x00', '字' * (todo.MAX_NOTE + 1)):
            with self.subTest(note=note[:20]), self.assertRaises(ValueError):
                self.change(state='ready_for_review', note=note)
        self.assertEqual(self.store.load(self.project['id']), before)

    def test_entire_card_edit_reopens_current_steps_and_preserves_old_notes(self):
        self.change(0, 0, 'ready_for_review', '原需求资料齐备待验')
        before = self.current()
        old_card = before['plans'][0]['cardId']
        # Unknown details participate in identity; edits outside known prompts
        # must not silently inherit manual readiness.
        cards = self.project['productionBrief']['plans']['activeSkill']['authorCards']
        cards[0]['details']['unknownFutureRequirement'] = '阶段切换时仍保留计数'
        self.project = self.store.save(self.project)
        after = self.current()
        self.assertNotEqual(after['plans'][0]['cardId'], old_card)
        self.assertTrue(all(step['workflowState'] == 'pending' for step in after['plans'][0]['makerSteps']))
        self.assertEqual(after['staleHistoryCount'], 1)
        self.assertEqual(after['workflowHistory'][0]['note'], '原需求资料齐备待验')

    def test_author_freetext_edit_reopens_same_card_and_preserves_history(self):
        self.change(0, 0, 'ready_for_review', '原动作资料齐备待验')
        before = self.current()
        old_card = before['plans'][0]['cardId']
        original_card = copy.deepcopy(before['plans'][0]['originalCard'])
        plan = self.project['productionBrief']['plans']['activeSkill']
        plan['authorDescription'] = '补充要求：形态结束或阶段切换时恢复原动作，并保留计数。'
        self.project = self.store.save(self.project)
        after = self.current()
        current = after['plans'][0]
        self.assertEqual(current['cardId'], old_card)
        self.assertEqual(current['originalCard'], original_card)
        self.assertNotEqual(current['requirementDigest'], before['plans'][0]['requirementDigest'])
        self.assertTrue(all(step['workflowState'] == 'pending' for step in current['makerSteps']))
        self.assertTrue(current['makerSteps'][0]['stale'])
        self.assertEqual(current['makerSteps'][0]['note'], '')
        self.assertEqual(after['workflowHistory'][0]['note'], '原动作资料齐备待验')
        self.assertEqual(after['staleHistoryCount'], 1)
        self.assertEqual(after['historySummary']['stale'], 1)
        self.assertFalse(after['gameReady'])

    def test_actual_reference_identity_change_invalidates_token_and_progress(self):
        cards = self.project['productionBrief']['plans']['abilities'][0]['authorCards']
        cards[0]['details'].update(referenceChoice='real-reference', referenceDigest='a' * 64)
        self.project = self.store.save(self.project)
        def reference(digest):
            return {'status': 'checked', 'identity': {'sha256': digest, 'inputs': ['bound-source']},
                    'gameReady': False, 'behaviorVerified': False}
        with mock.patch('author_reuse.inspect', return_value=reference('a' * 64)):
            self.change(1, 0, 'ready_for_review', '真实来源已核对，等待运行检查')
            previous = self.current()
        with mock.patch('author_reuse.inspect', return_value=reference('b' * 64)):
            after = self.current()
            step = after['plans'][1]['makerSteps'][0]
            self.assertEqual(step['workflowState'], 'pending')
            self.assertEqual(step['note'], '')
            self.assertTrue(step['stale'])
            self.assertEqual(step['historyCount'], 1)
            self.assertNotEqual(previous['token'], after['token'])
            plan = after['plans'][1]
            with self.assertRaisesRegex(ValueError, '预览已过期'):
                todo.update(self.store, self.project['id'], self.project['revision'], previous['token'],
                            plan['cardId'], step['id'], 'in_progress', '新来源待核对')
            self.change(1, 0, 'needs_help', '新来源需要协助核对')
            renewed = self.current()
        self.assertEqual(renewed['plans'][1]['makerSteps'][0]['workflowState'], 'needs_help')
        self.assertEqual(len(renewed['workflowHistory']), 2)
        self.assertEqual(renewed['staleHistoryCount'], 1)

    def test_changed_selected_reference_digest_reopens_even_without_byte_change(self):
        self.change(1, 0, 'ready_for_review', '原选定资料准备好待验')
        cards = self.project['productionBrief']['plans']['abilities'][0]['authorCards']
        cards[0]['details']['referenceDigest'] = 'c' * 64
        self.project = self.store.save(self.project)
        after = self.current()
        self.assertEqual(after['plans'][1]['makerSteps'][0]['workflowState'], 'pending')
        self.assertEqual(after['staleHistoryCount'], 1)

    def test_source_ledger_export_import_roundtrip_preserves_original_game_and_notes(self):
        self.change(0, 0, 'ready_for_review', '动作时序清单已准备，等待游戏检查')
        self.change(1, 2, 'needs_help', '需要制作方核对嵌套技能')
        original = copy.deepcopy(self.project)
        raw = self.store.export(self.project['id'])
        imported = self.store.import_archive(raw, name='制作待办.wfchar')
        self.assertEqual(imported['mechanicsTodo'], original['mechanicsTodo'])
        for key in ('nativeGameplay', 'notes', 'productionBrief', 'sounds', 'animations', 'effects'):
            self.assertEqual(imported[key], original[key], key)
        report = todo.report(self.store, imported)
        self.assertEqual(report['plans'][0]['makerSteps'][0]['workflowState'], 'ready_for_review')
        self.assertEqual(report['plans'][1]['makerSteps'][2]['workflowState'], 'needs_help')
        self.assertFalse(report['gameReady'])
        json.dumps(report, ensure_ascii=False, allow_nan=False)

    def test_untrusted_schema_unknown_fields_nested_values_and_size_are_rejected(self):
        self.change()
        valid = copy.deepcopy(self.project)
        todo.validate({})
        mutations = [lambda p: p.update(mechanicsTodo=None),
                     lambda p: p['mechanicsTodo'].update(schema='future'),
                     lambda p: p['mechanicsTodo'].update(gameReady=True),
                     lambda p: p['mechanicsTodo'].update(history={}),
                     lambda p: p['mechanicsTodo']['history'][0].update(behaviorVerified=True),
                     lambda p: p['mechanicsTodo']['history'][0].update(state=[]),
                     lambda p: p['mechanicsTodo']['history'][0].update(note={}),
                     lambda p: p['mechanicsTodo']['history'][0].update(requirementDigest='bad'),
                     lambda p: p['mechanicsTodo']['history'][0].update(cardId='../other'),
                     lambda p: p['mechanicsTodo']['history'][0].update(stepId=''),
                     lambda p: p['mechanicsTodo']['history'].extend([p['mechanicsTodo']['history'][0]] * todo.MAX_HISTORY)]
        for mutate in mutations:
            project = copy.deepcopy(valid)
            mutate(project)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                todo.validate(project)
        oversized = copy.deepcopy(valid)
        record = oversized['mechanicsTodo']['history'][0]
        record['note'] = '字' * todo.MAX_NOTE
        oversized['mechanicsTodo']['history'] = [record] * 200
        with self.assertRaisesRegex(ValueError, '总大小'):
            todo.validate(oversized)

    def test_unknown_historical_steps_are_retained_but_never_projected_as_ready(self):
        self.change()
        project = copy.deepcopy(self.project)
        row = copy.deepcopy(project['mechanicsTodo']['history'][0])
        row.update(stepId='retired-step', state='ready_for_review', note='旧步骤的历史资料')
        project['mechanicsTodo']['history'].append(row)
        plans = author_gameplay.preview(project, store=self.store)['integrationPlans']
        result = todo.report(self.store, project, plans)
        self.assertEqual(result['historySummary'], {'total': 2, 'current': 1, 'stale': 0,
                                                   'unknownCard': 0, 'unknownStep': 1})
        self.assertEqual(result['staleHistoryCount'], 1)
        self.assertEqual(len(result['workflowHistory']), 2)
        self.assertEqual(result['workflowCounts']['ready_for_review'], 0)
        self.assertFalse(result['gameReady'])

    def test_actual_store_save_and_archive_import_reject_forged_verification_metadata(self):
        self.change()
        bad = copy.deepcopy(self.project)
        bad['mechanicsTodo']['history'][0]['behaviorVerified'] = True
        with self.assertRaisesRegex(ValueError, '步骤记录格式'):
            self.store.save(bad)
        self.assertEqual(self.store.load(self.project['id']), self.project)
        files = archive_files(self.store.export(self.project['id']))
        project = json.loads(files['project.json'])
        project['mechanicsTodo']['gameReady'] = True
        files['project.json'] = json.dumps(project, ensure_ascii=False).encode('utf-8')
        before_count = len(self.store.list())
        with self.assertRaisesRegex(ValueError, '待办记录格式'):
            self.store.import_archive(make_zip(files))
        self.assertEqual(len(self.store.list()), before_count)


if __name__ == '__main__':
    unittest.main()
