"""Read-only per-card production plans, separate from native application.

Neither filled text nor a located reference proves runtime behavior. This
module derives from the existing brief and never rewrites animation or DSL.
"""
from __future__ import annotations

import copy
import re

import author_gameplay_complex as complex_rules
import native_gameplay as native

SCHEMA = 'starpoint-author-mechanics-plan-v1'
_SHA256 = re.compile(r'[0-9a-f]{64}\Z')
_TITLES = {'active_skill': '复杂主动技能', 'skill_reuse': '技能复用或再次施放',
           'special': '特殊能力与形态', 'summon': '召唤物与跟随物',
           'damage': '特殊伤害', 'custom': '特殊机制'}
_STEPS = {
    'active_skill': [('motion', '动作与定位', '核对起手、施法、恢复动作和锚点；原变换与时序保留。'),
                     ('hits', '目标与伤害', '核对对象、命中次数、伤害基准和每段时点。'),
                     ('playback', '特效与声音', '核对特效、声音的真实路径及播放时点。'),
                     ('repeat', '再次施放与中断', '核对耗能、冷却、重复施放和打断后的恢复。')],
    'skill_reuse': [('reference', '复用来源', '核对所选真实技能版本、动作和固定素材，不按名称猜引用。'),
                    ('target', '调用对象', '核对施放者、目标和基础/进化形态。'),
                    ('repeat', '再次施放规则', '核对耗能、触发次数、循环、冷却和打断恢复。')],
    'special': [('appearance', '形态与动作', '核对进入状态的模型、动作、特效和声音。'),
                ('behavior', '特殊能力执行', '核对触发、目标、主副位和状态中的实际行为。'),
                ('recovery', '结束与恢复', '核对结束、打断和阶段切换时的恢复动作与清理。'),
                ('repeat', '重复进入', '核对叠加、冷却和重复进入的规则。')],
    'summon': [('source', '召唤定义与素材', '按真实调用核对召唤类型、注册、本体、动作及复用来源。'),
               ('behavior', '召唤行为', '核对数量、寿命、移动、碰撞、攻击、目标和退场。'),
               ('nested', '技能与嵌套调用', '核对支持技能、嵌套召唤、循环和实际属性。'),
               ('runtime', '运行时选择与声音', '核对动态状态、等级、阶段保留、声音与资源加载。')],
    'damage': [('hits', '伤害规则', '核对技能/直攻/能力伤害、计算基准、目标、段数和属性耐性。'),
               ('playback', '命中与演出', '核对每段命中、动作、特效和声音时点。')],
    'custom': [('behavior', '实际执行方式', '核对原想法、触发、对象、次数和结束规则，不能用基础效果替代特殊要求。'),
               ('source', '素材与复用', '核对现有动作、技能、特效和声音来源。')],
}


def build(project, cards, pending=(), store=None):
    """Derive maker plans; author details stay distinct from execution checks."""
    plans = []
    cache = {}
    for item in cards:
        if item.get('state') != 'pending':
            continue
        card = item.get('card')
        card = card if isinstance(card, dict) else {}
        details = card.get('details')
        details = details if isinstance(details, dict) else {}
        mechanic = details.get('mechanic')
        if not isinstance(mechanic, str) or mechanic not in _TITLES:
            mechanic = 'active_skill' if item.get('plan') in ('activeSkill', 'pf') else 'custom'
        prompts = copy.deepcopy(item.get('detailPrompts') or complex_rules.assistance_prompts(item.get('plan'), card))
        provided = [row for row in prompts if row.get('status') == 'provided']
        missing = [row for row in prompts if row.get('status') == 'needed']
        choice, digest = details.get('referenceChoice'), details.get('referenceDigest')
        text_reference = details.get('reference')
        text_reference = text_reference if isinstance(text_reference, str) else ''
        reference = {'status': 'text_only' if text_reference.strip() else 'not_selected',
                     'label': text_reference, 'behaviorVerified': False, 'gameReady': False}
        if choice:
            if not isinstance(choice, str) or not isinstance(digest, str) or not _SHA256.fullmatch(digest):
                reference.update(status='pending', label='参考选择缺少有效来源身份，请重新选择或申请协助')
            elif store is None:
                reference.update(status='inspection_required', label='已选择工程参考，制作方继续核对来源')
            else:
                key = (choice, digest)
                if key not in cache:
                    from author_reuse import inspect
                    try:
                        cache[key] = inspect(store, project, choice, digest)
                    except (ValueError, OSError) as exc:
                        cache[key] = {'status': 'pending', 'label': '参考来源仍待核对',
                                      'evidence': [{'reason': str(exc)}], 'behaviorVerified': False, 'gameReady': False}
                reference = copy.deepcopy(cache[key])
        steps = [{'id': key, 'title': title, 'action': action, 'status': 'pending', 'owner': 'maker'}
                 for key, title, action in _STEPS[mechanic]]
        # Counted fields describe author information, never fulfilled behavior.
        plans.append({'cardId': item['id'], 'plan': item['plan'], 'planLabel': item['planLabel'],
                      'mechanic': mechanic, 'title': _TITLES[mechanic],
                      'text': card.get('text', '') if isinstance(card.get('text'), str) else '',
                      'originalCard': copy.deepcopy(item.get('card')), 'providedDetails': provided,
                      'missingDetails': missing, 'referenceCheck': reference, 'makerSteps': steps,
                      'status': 'maker_review', 'canAutoApply': False, 'behaviorVerified': False, 'gameReady': False})
    # Free text is carried literally, rather than assigned an inferred mechanic.
    free = [{'plan': item['plan'], 'planLabel': item['planLabel'], 'text': item['text'],
             'status': 'maker_review', 'behaviorVerified': False, 'gameReady': False}
            for item in pending if item.get('text')]
    for plan in plans:
        plan['additionalRequirements'] = [copy.deepcopy(item) for item in free if item['plan'] == plan['plan']]
    result = {'schema': SCHEMA, 'projectIdentity': {'id': project.get('id'), 'revision': project.get('revision')},
            'token': native.digest({'id': project.get('id'), 'revision': project.get('revision'),
                                    'plans': plans, 'freeRequirements': free}),
            'plans': plans, 'freeRequirements': free, 'planCount': len(plans),
            'missingInformationCount': sum(len(item['missingDetails']) for item in plans),
            'gameReady': False, 'note': '已说明的内容继续保留；素材参考查到也不表示行为已接入，制作方仍需逐步实现和验证。'}
    from mechanics_todo import merge
    return merge(result, project)
