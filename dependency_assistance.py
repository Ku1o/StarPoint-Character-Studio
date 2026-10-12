"""Read-only author help derived from actual pending evidence and intentions.

This report does not change author declarations, supply missing files or mark
technical work complete. Paths and table diagnostics stay in the technical
report; artists get questions about behavior, appearance and reusable sources.
"""
from __future__ import annotations

import hashlib
import json

SCHEMA = 'character-dependency-assistance-v1'
DOMAIN_GUIDES = {
    'definition': ('玩法参考', '说明希望参考哪个角色及哪一种形态；已有工程可以直接提供。',
                   '读取和校验真实角色定义，保留旧行；缺少或非法数据由接入方处理。'),
    'skill': ('主动技能', '说明发动后先后发生什么、命中几次、作用于谁；希望复用时写角色和技能名称。',
              '核对动作、效果、命中、声音与回调中的引用，复用资源仍需验证来源。'),
    'pixelart': ('角色动作', '已有待机、施法和恢复动作可复用；缺画稿时说明姿态、足底与恢复方式。',
                 '核对小人动作、图块、定位和恢复引用，不让作者填写资源路径。'),
    'special': ('特殊能力表现', '说明变身、特殊动作或状态的外观、开始与结束时机；可写希望复用的参考。',
                '核对特殊动作和能力实际调用的图标、效果与表定义。'),
    'ability': ('能力与队长效果', '说明触发条件、目标、数值单位、持续时间与重复触发规则；不确定的部分可以请协助。',
                '核对真实条件、主副位规则、额外能力及特殊效果；确认表数据和执行语义。'),
    'summon': ('召唤物与跟随物', '说明外观、出现数量、存活多久、如何移动和攻击、消失方式；已有角色动作和技能可以作为复用参考。',
               '补齐召唤物注册、模型与动作、支持技能、嵌套召唤及声音，检查递归和循环。'),
    'powerFlip': ('强化弹射', '说明职业、各等级表现及是否切换；可以复用已有职业或角色的效果。',
                  '核对实际职业表、替换定义、三个等级动作和支持技能。'),
    'shared': ('角色复用的公共素材', '状态图标、命中闪光和通用特效通常可复用；只需说明角色希望使用的表现或参考，缺少素材可以申请协助，不需要写代码。',
               '核对角色实际调用的公共特效、图标与战斗条件，验证复用来源；游戏通用界面另留技术报告，不作为稿主缺项。'),
    'ui': ('战斗界面图片', '立绘母版可派生头像和小图；说明是否沿用原图，缺少母版时申请协助。',
           '核对实际战斗界面读取、图集与图块。'),
    'cutin': ('技能切入图', '可沿用基础或进化立绘；只需说明希望使用哪张图。',
              '核对各形态独立切入图的真实引用。'),
}


def _domain(item):
    explicit = item.get('domain')
    if explicit not in DOMAIN_GUIDES:
        explicit = item.get('category')
    if explicit in DOMAIN_GUIDES:
        return explicit
    text = ' '.join(str(item.get(key) or '') for key in ('requester', 'source', 'logical', 'reason')).lower()
    if any(word in text for word in ('summon', 'multiball', 'funnel', 'zako', '召唤')):
        return 'summon'
    if any(word in text for word in ('powerflip', 'power_flip', '强化弹射')):
        return 'powerFlip'
    if any(word in text for word in ('ability', 'leader', '能力')):
        return 'ability'
    if any(word in text for word in ('common', 'attention', '公共', 'shared')):
        return 'shared'
    if 'special' in text:
        return 'special'
    if any(word in text for word in ('pixelart', 'sprite_sheet')):
        return 'pixelart'
    if 'cutin' in text:
        return 'cutin'
    if 'ui/' in text:
        return 'ui'
    return 'skill'


def _identity(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()[:20]


def build(project, closure=None, gameplay=None):
    """Group observed gaps without confusing technical work with author debts."""
    grouped = {}
    technical = []
    if closure:
        for key in ('missingReferences', 'unresolvedDynamic', 'unsupported', 'scopeGaps',
                    'characterSemanticGaps', 'sourceDefinitionProblems', 'referenceReadErrors'):
            for raw in closure.get(key, []):
                item = dict(raw) if isinstance(raw, dict) else {'reason': str(raw)}
                evidence = {'kind': key, **item}
                if item.get('resourceOwner') == 'game-common-ui':
                    if evidence not in technical:
                        technical.append(evidence)
                    continue
                bucket = grouped.setdefault(_domain(item), [])
                if evidence not in bucket:
                    bucket.append(evidence)
    requests = []
    for domain, evidence in grouped.items():
        title, author, maker = DOMAIN_GUIDES[domain]
        requests.append({'id': _identity([domain, evidence]), 'domain': domain,
                         'title': title + '待核对', 'owner': 'maker',
                         'reason': '已发现缺少的引用或尚未验证的分支，需要接入方继续核对。',
                         'authorInput': author, 'makerAction': maker,
                         'reuse': '已提供的原稿、角色工程和明确复用参考继续保留，不必重复提供。',
                         'observedItems': len(evidence), 'evidence': evidence,
                         'requestText': title + '：请协助核对素材与游戏接入。' + author + '\n制作方：' + maker,
                         'integrationVerified': False})
    if gameplay:
        mechanics = {item['cardId']: item for item in (gameplay.get('integrationPlans') or {}).get('plans', [])}
        for item in gameplay.get('items', []):
            if item.get('status') in ('supported', 'applied'):
                continue
            title = (item.get('planLabel') or '玩法') + '方案待协助'
            questions = item.get('detailPrompts') or [
                '什么时候触发，条件要同时满足还是任一满足？',
                '影响谁，数值按百分比、倍数还是固定值计算？',
                '持续多久，重复触发如何叠加或刷新？',
                '召唤物或特殊动作的外观、数量、攻击与结束方式是什么？',
            ]
            questions = [((question.get('label') or '补充说明') + ('：已说明“' + question['value'] + '”' if question.get('value') else '：可以补充或请协助'))
                         if isinstance(question, dict) else str(question) for question in questions]
            plan = mechanics.get(item.get('id'), {})
            provided = plan.get('providedDetails', [])
            missing = plan.get('missingDetails', [])
            maker_steps = plan.get('makerSteps', [])
            if plan:
                questions = [('已说明：' + row['label'] + '：' + row['value']) for row in provided]
                questions += [(row['label'] + '：可以补充或请协助') for row in missing]
                if not questions:
                    questions = ['作者信息已保留，制作方继续核对实际执行。']
            maker = ('按制作步骤继续核对：' + '；'.join(row['title'] for row in maker_steps) + '。'
                     if maker_steps else '先核对原方案与实际执行，再实现或提出可接受的替代方案。')
            requests.append({'id': _identity(['card', item.get('id'), item.get('reason'), plan]),
                             'domain': 'gameplay', 'title': title, 'owner': 'author-and-maker',
                             'plan': item.get('plan'), 'text': item.get('text') or '',
                             'reason': item.get('reason') or '目前不能自动接入，原方案保留。',
                             'authorInput': ' '.join(questions),
                             'makerAction': maker,
                             'providedDetails': provided, 'missingDetails': missing,
                             'makerSteps': maker_steps, 'referenceCheck': plan.get('referenceCheck'),
                             'reuse': '可以说明已有角色、动作或素材作为参考；不需要作者编写程序。',
                             'requestText': title + '：' + (item.get('text') or '') + '\n请协助：' + (item.get('reason') or '核对实际玩法。') + '\n作者资料：' + ' '.join(questions) + '\n制作方：' + maker,
                             'integrationVerified': False})
        for item in gameplay.get('pending', []):
            if not item.get('text'):
                continue
            title = (item.get('planLabel') or '玩法') + '补充说明待核对'
            requests.append({'id': _identity(['free', item.get('plan'), item['text']]),
                             'domain': 'gameplay', 'title': title, 'owner': 'maker',
                             'text': item['text'], 'reason': item.get('pendingNextAction') or '交接方逐项核对。',
                             'authorInput': '现有说明保留，可以补充参考角色或可接受的调整。',
                             'makerAction': '保留作者说明，逐项核对执行方式、素材和验收。',
                             'reuse': '部分卡片已接入仍不代表这段说明已完成。',
                             'requestText': title + '：请结合已保存的作者说明逐项核对。',
                             'integrationVerified': False})
    technical_requests = ([{'domain': 'game-common-ui', 'owner': 'maker', 'title': '游戏通用界面技术核验',
                           'authorInputRequired': False, 'evidence': technical,
                           'makerAction': '核对既有公共界面的素材来源和运行时绑定，不作为MOD角色稿主缺项。'}] if technical else [])
    return {'schema': SCHEMA, 'projectIdentity': {'id': project.get('id'), 'revision': project.get('revision')},
            'technicalRequests': technical_requests,
            'requests': requests, 'requestCount': len(requests), 'gameReady': False,
            'note': '技术缺口由接入方核对；作者只需说明希望的行为、外观和复用参考。保存协助说明不会补出素材或完成验收。'}
