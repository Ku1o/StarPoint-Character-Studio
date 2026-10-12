"""Portable, manual maker progress; never a receipt of game behavior.

The ledger is additive metadata. Plans and source checks are always rebuilt
from the current project. Only ``update`` writes, through the existing store.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re

SCHEMA = 'starpoint-mechanics-todo-v1'
REPORT_SCHEMA = 'starpoint-mechanics-todo-report-v1'
STATE_LABELS = {'pending': '待处理', 'in_progress': '处理中',
                'needs_help': '待协助', 'ready_for_review': '准备好待验'}
MAX_HISTORY = 5000
MAX_BYTES = 2 * 1024 * 1024
MAX_NOTE = 4000
_ID = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_RECORD_KEYS = {'cardId', 'requirementDigest', 'stepId', 'state', 'note'}
NOTE = '手工进度只说明资料或制作准备情况；准备好待验仍需制作方与游戏验证，不表示行为已接入。'


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _identifier(value, label):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(label + '无效')


def _state_note(state, note):
    if not isinstance(state, str) or state not in STATE_LABELS:
        raise ValueError('制作待办状态无效')
    if not isinstance(note, str) or len(note) > MAX_NOTE or '\x00' in note:
        raise ValueError('制作待办说明必须是有效文字且不超过4000字')
    if state == 'ready_for_review' and not note.strip():
        raise ValueError('准备好待验时请说明已准备的资料、制作结果或证据')


def validate(project):
    """Reject untrusted schemas and oversized metadata; old projects need none."""
    if 'mechanicsTodo' not in project:
        return
    ledger = project['mechanicsTodo']
    if not isinstance(ledger, dict) or set(ledger) != {'schema', 'history'} or ledger['schema'] != SCHEMA:
        raise ValueError('制作待办记录格式无效')
    history = ledger['history']
    if not isinstance(history, list) or len(history) > MAX_HISTORY:
        raise ValueError('制作待办历史记录超限或无效')
    # Check each scalar before encoding, so nested/cyclic untrusted values do
    # not get a chance to consume a recursive serialization budget.
    size = len(_canonical({'schema': SCHEMA, 'history': []}))
    for record in history:
        if not isinstance(record, dict) or set(record) != _RECORD_KEYS:
            raise ValueError('制作待办步骤记录格式无效')
        _identifier(record['cardId'], '制作待办卡片编号')
        _identifier(record['stepId'], '制作待办步骤编号')
        digest = record['requirementDigest']
        if not isinstance(digest, str) or not _SHA.fullmatch(digest):
            raise ValueError('制作待办需求身份无效')
        _state_note(record['state'], record['note'])
        try:
            size += len(_canonical(record)) + 1
        except (TypeError, ValueError, UnicodeError) as exc:
            raise ValueError('制作待办记录无法保存') from exc
        if size > MAX_BYTES:
            raise ValueError('制作待办记录总大小超限')


def requirement_digest(plan):
    """Bind full author intent and currently inspected reference identity."""
    reference = plan.get('referenceCheck') or {}
    return _digest({'card': plan.get('originalCard'), 'plan': plan.get('plan'),
                    'mechanic': plan.get('mechanic'),
                    'additionalRequirements': plan.get('additionalRequirements', []),
                    'sourceIdentity': reference.get('identity'),
                    'referenceStatus': reference.get('status'),
                    'steps': [{'id': item['id'], 'action': item.get('action')}
                              for item in plan.get('makerSteps', [])]})


def merge(plan_report, project):
    """Return current plans plus progress without changing either input.

    Existing plan ``token`` and step ``status`` retain their original meaning.
    ``todoToken`` is the token accepted by update; it also binds history.
    This function imports no plan builder, so builders can call it safely.
    """
    validate(project)
    result = copy.deepcopy(plan_report)
    history = project.get('mechanicsTodo', {}).get('history', [])
    latest, seen, by_step = {}, set(), {}
    for record in history:
        latest[(record['cardId'], record['requirementDigest'], record['stepId'])] = record
        by_step.setdefault((record['cardId'], record['stepId']), []).append(record)
    counts = dict.fromkeys(STATE_LABELS, 0)
    for plan in result.get('plans', []):
        digest = requirement_digest(plan)
        plan['requirementDigest'] = digest
        for step in plan.get('makerSteps', []):
            key = (plan['cardId'], digest, step['id'])
            seen.add(key)
            record = latest.get(key)
            prior = by_step.get((plan['cardId'], step['id']), [])
            stale = any(row['requirementDigest'] != digest for row in prior)
            state = record['state'] if record else 'pending'
            step.update(workflowState=state, workflowLabel=STATE_LABELS[state],
                        note=record['note'] if record else '', stale=stale,
                        historyCount=len(prior), behaviorVerified=False, gameReady=False,
                        evidenceNote='待办说明为手工制作记录；' + str(step.get('action') or '') +
                                     (' 需求或参考已变化，旧记录保留，当前需重新核对。' if stale and not record else ''))
            counts[state] += 1
        plan['workflowNote'] = NOTE
    bindings = [{'cardId': plan['cardId'], 'requirementDigest': plan['requirementDigest']}
                for plan in result.get('plans', [])]
    current_cards = {plan['cardId']: plan for plan in result.get('plans', [])}
    summary = {'total': len(history), 'current': 0, 'stale': 0, 'unknownCard': 0, 'unknownStep': 0}
    for row in history:
        plan = current_cards.get(row['cardId'])
        if plan is None:
            summary['unknownCard'] += 1
        elif row['requirementDigest'] != plan['requirementDigest']:
            summary['stale'] += 1
        elif row['stepId'] not in {step['id'] for step in plan['makerSteps']}:
            summary['unknownStep'] += 1
        else:
            summary['current'] += 1
    result.update(todoToken=_digest({'id': project.get('id'), 'revision': project.get('revision'),
                                        'planToken': plan_report.get('token'), 'bindings': bindings,
                                        'history': history}),
                  revision=project.get('revision'), todoStates=copy.deepcopy(STATE_LABELS),
                  workflowCounts=counts, workflowHistory=copy.deepcopy(history),
                  historySummary=summary,
                  staleHistoryCount=sum((row['cardId'], row['requirementDigest'], row['stepId']) not in seen
                                        for row in history),
                  workflowNote=NOTE, behaviorVerified=False, gameReady=False)
    return result


def report(store, project, plan_report=None):
    """Read current complete gameplay plans and portable maker history."""
    if plan_report is None:
        from author_gameplay import preview
        plan_report = preview(project, store=store)['integrationPlans']
    plans = plan_report
    result = merge(plans, project)
    result.update(schema=REPORT_SCHEMA, planSchema=plans.get('schema'),
                  planToken=plans.get('token'), token=result['todoToken'])
    return result


def update(store, pid, revision, token, card_id, step_id, state, note):
    """Append one current-step note, reject stale callers, save one project."""
    if type(revision) is not int or revision < 0:
        raise ValueError('制作待办工程版本无效')
    if not isinstance(token, str) or not _SHA.fullmatch(token):
        raise ValueError('制作待办预览身份无效')
    _identifier(card_id, '制作待办卡片编号')
    _identifier(step_id, '制作待办步骤编号')
    _state_note(state, note)
    project = store.load(pid)
    validate(project)
    if project['revision'] != revision:
        raise ValueError('工程已更新，请重新保存并查看制作待办')
    current = report(store, project)
    if current['token'] != token:
        raise ValueError('制作待办预览已过期，请重新查看')
    plan = next((item for item in current['plans'] if item['cardId'] == card_id), None)
    if plan is None or not any(item['id'] == step_id for item in plan['makerSteps']):
        raise ValueError('只能更新当前方案中已有的制作步骤')
    incoming = copy.deepcopy(project)
    ledger = incoming.setdefault('mechanicsTodo', {'schema': SCHEMA, 'history': []})
    ledger['history'].append({'cardId': card_id, 'requirementDigest': plan['requirementDigest'],
                              'stepId': step_id, 'state': state, 'note': note})
    validate(incoming)
    return store.save(incoming)
