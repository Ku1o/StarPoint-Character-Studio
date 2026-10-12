"""Explicit, bounded Chinese author cards -> real native ability rows.

This module edits portable projects only. It never allocates game IDs, installs
resources, rewrites a retained source definition, or reports game readiness.
"""
from __future__ import annotations

import copy
import re
from collections import Counter
from decimal import Decimal, InvalidOperation

import native_gameplay as native
import author_gameplay_complex as complex_rules
from ability_editor import validate_row

SCHEMA = "starpoint-author-gameplay-integration-v1"
MAX_HISTORY = 10
MAX_CARDS = 256
MAX_META_BYTES = 8 * 1024 * 1024
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_PERCENT = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(?:%|％)\Z")
_SECONDS = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(?:秒|s|seconds?)\Z", re.I)
_PERMANENT = {"永久", "全程", "常驻", "持续到战斗结束"}
_TRIGGERS = {"battle_start": ("战斗开始时", "0"), "skill": ("自己使用技能时", "23"),
             "power_flip": ("发动强化弹射时", "2"), "always": ("全程持续生效", "0")}
_EFFECTS = {
    "attack_up": ("攻击力提高", "0", "ConditionAttackPoint", "32", "AttackPoint"),
    "skill_damage_up": ("技能伤害提高", "1", "ConditionSkillDamage", "34", "SkillDamage"),
    "direct_damage_up": ("直接攻击伤害提高", "214", "ConditionDirectDamage", "33", "DirectDamage"),
    "power_flip_up": ("强化弹射伤害提高", "28", "ConditionPowerFlipDamage", "55", "PowerFlipDamage"),
    "heal": ("按最大生命值比例恢复生命", None, None, "206", "RatioHeal"),
    "combo_add": ("追加本次战斗连击", None, None, "226", "AddCombo"),
    "skill_gauge_up": ("技能槽增加", None, None, "211", "SkillGauge"),
}
_TARGETS = {"self": ("自己", "0"), "party": ("全队（包括自己）", "5"),
            "element_party": ("同属性队友（不含自己）", "1"), "battle_combo": ("本次战斗连击", "0")}
_GROUPS = ("Red", "Blue", "Yellow", "Green", "White", "Black")
_ALLOWED_CARD_FIELDS = {"trigger", "target", "effect", "amount", "duration", "text",
                        "healBasis", "stacking", "mainOnly", "conditions", "details"}


def _plans(project):
    plans = (project.get("productionBrief") or {}).get("plans") or {}
    yield "activeSkill", "主动技能", None, plans.get("activeSkill") or {}
    yield "leader", "队长技", "leader", plans.get("leader") or {}
    yield "pf", "强化弹射动作", None, plans.get("pf") or {}
    abilities = plans.get("abilities") or []
    if not isinstance(abilities, list) or len(abilities) > 6:
        raise ValueError("能力方案需要最多六个槽位")
    for index, plan in enumerate(abilities):
        if not isinstance(plan, dict):
            raise ValueError("能力方案结构无效")
        yield "ability" + str(index), "能力 " + str(index + 1), index + 1, plan


def catalog():
    """Small author-facing menu; enum IDs are implementation details only."""
    return {"schema": SCHEMA, "gameReady": False,
            "plans": ["leader", *["ability" + str(i) for i in range(6)]],
            "triggers": [{"id": key, "label": value[0]} for key, value in _TRIGGERS.items()],
            "targets": [{"id": key, "label": value[0]} for key, value in _TARGETS.items()],
            "effects": [{"id": key, "label": value[0], "amountUnit": "count" if key == "combo_add" else "percent",
                         "targets": ["battle_combo"] if key == "combo_add" else ["self", "party", "element_party"],
                         "durationMode": "instant" if key in ("heal", "combo_add", "skill_gauge_up") else "timed_or_permanent"}
                        for key, value in _EFFECTS.items()],
            "durationHint": "增益需明确填写秒数；战斗开始或全程增益可填写“永久”。",
            "stacking": [{"id": "single", "label": "这条增益只保留一层（重复触发不叠加）"}],
            "healBasis": [{"id": "maximum_hp", "label": "按目标最大生命值比例"}],
            "pendingNextAction": "特殊伤害、命中/受伤触发、主动动作、叠层和其他机制保留说明，交接方核对实际客户端支持后实现。",
            "note": "只追加明确选择的能力或队长条目；原技能动作、原行与原始定义保持。单层规则仅针对这条增益卡，重复触发取较长剩余时间，其他来源仍可共存。追加连击是每次触发增加计数，不是状态叠层。技能槽增加仍沿游戏获取限制，不保证每次获得。游戏实战、形态和正式资源键接入仍需验证。",
            **complex_rules.catalog()}


def _hash(value):
    return native.digest(value)


def _card_id(plan, index, card):
    return _hash({"plan": plan, "index": index, "card": card})


def _percent(value):
    match = _PERCENT.fullmatch(value.strip()) if isinstance(value, str) else None
    if not match:
        raise ValueError("请明确填写百分比，例如 20%；不能把“20”或“2倍”猜成增益百分比")
    try:
        number = Decimal(match[1])
        if not number.is_finite() or number <= 0:
            raise ValueError()
        native.scaled(number, 1000, "百分比")
        return number
    except (InvalidOperation, ValueError):
        raise ValueError("百分比需要是可精确编码的正数")


def _human_description(data, card, amount, seconds, conditions):
    """Describe only verified, used properties, with author-facing units."""
    trigger = "战斗开始时" if card["trigger"] == "always" else _TRIGGERS[card["trigger"]][0]
    prefix = trigger + "，"
    if conditions:
        prefix += "同时满足" + "、".join(value["description"] for value in conditions) + "时，"
    target = _TARGETS[card["target"]][0]
    if card["target"] == "element_party":
        source = data["source"]["data"]["character"]
        element = source["records"]["character"]["selected"][source["id"]]["rows"][0][3]
        target = ("火", "水", "雷", "风", "光", "暗")[int(element)] + "属性队友（不含自己，沿用玩法参考）"
    value = format(amount.normalize(), "f") if isinstance(amount, Decimal) else str(amount)
    if card["effect"] == "combo_add":
        body = "本次战斗连击增加" + value + "。"
    elif card["effect"] == "heal":
        body = target + "恢复各自最大生命值的" + value + "%。"
    elif card["effect"] == "skill_gauge_up":
        body = target + "尝试增加各自基础最大技能槽的" + value + "%，仍沿游戏获取限制。"
    else:
        duration = "基础持续" + format(seconds.normalize(), "f") + "秒" if seconds else "持续到战斗结束"
        body = target + _EFFECTS[card["effect"]][0] + value + "%，" + duration + "。"
        if seconds:
            body += "这条增益不叠加，重复触发取较长剩余时间。"
    if card.get("mainOnly"):
        body += "携带角色须处于主位。"
    if conditions:
        body += complex_rules.CONDITION_NOTE
    return prefix + body


def _generated_row(data, slot, card):
    """Use resolved enum names and an installed, verified template, never guesses."""
    if not isinstance(card, dict) or set(card) - _ALLOWED_CARD_FIELDS:
        raise ValueError("卡片包含未支持的条件或参数，请保留原说明并申请协助")
    if "text" in card and not isinstance(card["text"], str):
        raise ValueError("卡片文字需要是可读文字；原始内容继续保留待核")
    if any(not isinstance(card.get(key), str) for key in ("trigger", "target", "effect")):
        raise ValueError("触发、目标和效果需要是明确的中文选项，请保留卡片并核对")
    complex_rules.check_details(card)
    conditions = complex_rules.parse_conditions(card)
    trigger = _TRIGGERS.get(card.get("trigger"))
    effect = _EFFECTS.get(card.get("effect"))
    target = _TARGETS.get(card.get("target"))
    if not trigger:
        raise ValueError("这个触发尚未核实，不能自动转换；请说明触发对象、次数和条件")
    if not effect:
        raise ValueError("这个效果尚未核实，不能自动转换；伤害需说明分类、基准、段数和对象")
    if not target:
        raise ValueError("这个目标尚未核实；敌人目标不能套用角色增益目标")
    is_combo = card.get("effect") == "combo_add"
    if is_combo != (card.get("target") == "battle_combo"):
        raise ValueError("追加连击影响本次战斗连击，不能当作自身或队伍增益；其他效果也不能套用战斗连击目标")
    amount = complex_rules.integer(card.get("amount"), minimum=1) if is_combo else _percent(card.get("amount"))
    duration = card.get("duration", "")
    if not isinstance(duration, str):
        raise ValueError("持续时间需要是文字秒数或明确的永久说明")
    duration = duration.strip()
    main_only = card.get("mainOnly", False)
    if not isinstance(main_only, bool):
        raise ValueError("主位限定必须是明确的开关")
    if slot == "leader" and main_only:
        raise ValueError("队长条件由队长槽位决定，请勿另加主位限定")
    if slot != "leader":
        current, _ = native.group_for(data, slot)
        if current["rows"] and current["rows"][0][1] == "false" and not main_only:
            raise ValueError("原能力组首条限定主位，新增副位可用卡无法生效。原首条保持；请选择主位限定，或交接方核对整组条件。")
    if is_combo:
        if duration or card.get("trigger") == "always" or card.get("stacking") not in (None, "", "unmarked"):
            raise ValueError("追加连击是每次具体触发增加计数，不支持持续时间、持续生效或单层状态规则；请保留未确定的重复规则")
        effect_kind, effect_name, seconds = effect[3], effect[4], None
    elif card.get("effect") == "heal":
        if card.get("healBasis") != "maximum_hp":
            raise ValueError("请明确选择“按最大生命值比例回复”；当前生命值或固定回复量需另行核实")
        if amount > 100 or duration or card.get("trigger") == "always":
            raise ValueError("比例治疗是一次回复（0%至100%），不支持持续回复或永久治疗")
        effect_kind, effect_name, seconds = effect[3], effect[4], None
    elif card.get("effect") == "skill_gauge_up":
        if amount > 100 or duration or card.get("trigger") == "always" or card.get("stacking") not in (None, "", "unmarked") or "details" in card:
            raise ValueError("技能槽增加需为0%以上至100%的百分比及具体触发；持续、叠层或特殊机制继续申请协助，游戏获取限制保持")
        effect_kind, effect_name, seconds = effect[3], effect[4], None
    elif duration in _PERMANENT:
        if card.get("trigger") not in ("battle_start", "always"):
            raise ValueError("重复触发的永久增量可能累积；请明确持续秒数，或交接方设计叠层上限")
        if card.get("stacking") not in (None, "", "single"):
            raise ValueError("自定义叠层尚未支持，请保留规则并申请协助")
        effect_kind, effect_name, seconds = effect[3], effect[4], None
    else:
        match = _SECONDS.fullmatch(duration)
        if not match:
            raise ValueError("请写清增益持续秒数，例如 10秒；留空不能自动当成永久")
        seconds = Decimal(match[1])
        if seconds <= 0 or card.get("trigger") == "always":
            raise ValueError("有时限的增益需要具体的开始触发和正数秒数")
        native.scaled(seconds, 6000000, "持续时间")
        if card.get("stacking") != "single":
            raise ValueError("请明确选择单层增益；自定义叠层、刷新与延长规则需交接方核实")
        effect_kind, effect_name = effect[1], effect[2]
    # Verify symbolic enums against the bundled parser contract, not merely int type.
    enum = native.composer.composer_meta()["enums"]["instant_content"].get(effect_kind)
    if not enum or enum.get("en") != effect_name:
        raise ValueError("当前客户端效果定义与已核实模板不一致，请由接入方更新定义")
    groups = ""
    if card.get("target") == "element_party":
        source = data["source"]["data"]["character"]
        row = source["records"]["character"]["selected"][source["id"]]["rows"][0]
        if row[3] not in tuple(str(i) for i in range(6)):
            raise ValueError("参考角色属性不明确，不能猜测同属性队友")
        groups = _GROUPS[int(row[3])]
    generated = native.composer.generate("L:author" if slot == "leader" else "author",
        mode="instant", trigger_kind=trigger[1], effect_kind=effect_kind,
        effect_unit="count" if is_combo else "pct", value=str(amount), target=target[1], groups=groups,
        blank_factory=native.blank_factory(data, slot))
    row, kind = generated["row"], generated["kind"]
    blocks = native.describe.layout(kind)["blocks"]
    # These are explicit properties of this supported template. Inherited blank
    # defaults must not add conditions, hidden targets, limits or extra strengths.
    for name in ("precondition1", "precondition2", "precondition3"):
        row[blocks[name]] = "0"
    if main_only:
        condition = native.composer.composer_meta()["enums"]["precondition"].get("202")
        if not condition or condition.get("en") != "OwnerIsMain":
            raise ValueError("当前定义未核实主位条件，不能只靠显示标志生成")
        # The first row controls whole-group unison admission. A later row's
        # display flag is insufficient to restrict its actual execution.
        row[blocks["precondition1"]] = "202"
    row[blocks["instant_precontent"]] = "(None)"
    row[blocks["instant_delay"]] = "0"
    base = blocks["instant_trigger"]
    row[base + 1] = "0"  # own trigger source
    row[base + 2] = row[base + 9] = ""
    row[base + 3] = row[base + 4] = "0" if trigger[1] == "0" else "100000"
    row[base + 5] = row[base + 6] = "0"
    row[base + 7] = "(None)"
    row[base + 8] = "0"
    base = blocks["instant_content"]
    for offset in (6, 7, 8, 9, 12, 13, 27, 29, 30, 32, 33):
        row[base + offset] = "0"
    row[base + 10] = row[base + 11] = native.scaled(seconds, 6000000, "持续时间") if seconds else "0"
    if seconds:
        # Native MemberImpl builds `number` condition results. Zero is an empty
        # result, even when strength/frame types are valid. 100000 resolves to
        # one application; initial_multiply is an unscaled integer multiplier.
        row[base + 12] = row[base + 13] = "100000"
        row[base + 27] = "1"
    for offset in (14, 15, 16, 17, 18, 22, 34):
        row[base + offset] = "(None)"
    for offset in (19, 21, 23, 24, 31, 35, 36, 37):
        row[base + offset] = ""
    row[base + 20] = "0"  # do not silently make a condition undispellable
    row[base + 25] = "false"
    row[base + 26] = row[base + 28] = "0"
    if kind == "ability":
        row[1] = "false" if main_only else "true"
    complex_rules.write_conditions(row, kind, card, conditions)
    validate_row(kind, row)
    description = _human_description(data, card, amount, seconds, conditions)
    return row, kind, description


def validate(project):
    """Validate additive receipts without invalidating old projects."""
    value = project.get("authorGameplayIntegration")
    if value is None:
        return
    if not isinstance(value, dict) or set(value) != {"schema", "history"} or value.get("schema") != SCHEMA:
        raise ValueError("作者玩法接入记录版本不支持")
    history = value.get("history")
    if not isinstance(history, list) or len(history) > MAX_HISTORY or len(native.canonical(value)) > MAX_META_BYTES:
        raise ValueError("作者玩法接入记录过大")
    for receipt in history:
        if not isinstance(receipt, dict) or set(receipt) != {"token", "beforeHash", "afterHash", "sourceHash", "groups", "cards", "readback", "gameReady"}:
            raise ValueError("作者玩法接入回执结构无效")
        if any(not isinstance(receipt.get(key), str) or not _HEX.fullmatch(receipt[key])
               for key in ("token", "beforeHash", "afterHash", "sourceHash")):
            raise ValueError("作者玩法接入回执校验无效")
        if receipt["readback"] is not True or receipt["gameReady"] is not False:
            raise ValueError("作者玩法接入回执不能冒充游戏验收")
        groups = receipt["groups"]
        if not isinstance(groups, dict) or not groups or len(groups) > 7:
            raise ValueError("作者玩法撤回快照无效")
        for key, rows in groups.items():
            if key not in ("leader", *["ability" + str(i) for i in range(6)]) or not isinstance(rows, list) or len(rows) > 128:
                raise ValueError("作者玩法撤回槽位无效")
            for row in rows:
                native._validate_row(row, "leader_ability" if key == "leader" else "ability", draft=True)
        cards = receipt["cards"]
        if not isinstance(cards, list) or not cards or len(cards) > MAX_CARDS:
            raise ValueError("作者玩法卡片回执无效")
        for card in cards:
            if not isinstance(card, dict) or set(card) != {"id", "plan", "index", "cardHash", "rowHash", "description"}:
                raise ValueError("作者玩法卡片记录无效")
            if card["plan"] not in groups or type(card["index"]) is not int or not 0 <= card["index"] < MAX_CARDS:
                raise ValueError("作者玩法卡片位置无效")
            if any(not isinstance(card[key], str) or not _HEX.fullmatch(card[key]) for key in ("id", "cardHash", "rowHash")):
                raise ValueError("作者玩法卡片身份无效")
            if not isinstance(card["description"], str) or len(card["description"]) > 4000:
                raise ValueError("作者玩法卡片说明过长")


def preview(project, store=None):
    """Read only: report every card and free-text remainder, never discard intent."""
    validate(project)
    data = project.get("nativeGameplay")
    plans = list(_plans(project))
    token = _hash({"id": project.get("id"), "revision": project.get("revision"),
                   "nativeGameplay": data, "plans": (project.get("productionBrief") or {}).get("plans"),
                   "integration": project.get("authorGameplayIntegration")})
    blockers, rows, pending = [], [], []
    if not data:
        blockers.append("尚未选择真实角色玩法定义。请先选择与美术模板一致的参考角色；不会生成空白游戏骨架。")
    else:
        try:
            native.validate_native(data)
        except ValueError as error:
            blockers.append("原有游戏条目仍有问题，已原样保留：" + str(error))
    history = (project.get("authorGameplayIntegration") or {}).get("history") or []
    applied = {card["id"]: card for receipt in history for card in receipt["cards"]}
    positions = {(card["plan"], card["index"]): card for receipt in history for card in receipt["cards"]}
    # Receipts record an earlier application, not current truth. Count matching
    # rows as well as hashes so deleting one of two identical additions cannot
    # be hidden by the surviving copy (or an identical original row).
    required_rows, current_rows = {}, {}
    for receipt in history:
        for plan, original_rows in receipt["groups"].items():
            if plan not in required_rows:
                required_rows[plan] = Counter(_hash(row) for row in original_rows)
        for applied_card in receipt["cards"]:
            required_rows[applied_card["plan"]][applied_card["rowHash"]] += 1
    if data and not blockers:
        for plan in required_rows:
            slot = "leader" if plan == "leader" else int(plan[7:]) + 1
            group, _ = native.group_for(data, slot)
            current_rows[plan] = Counter(_hash(row) for row in group["rows"])
    for plan_key, label, slot, plan in plans:
        cards = plan.get("authorCards") or []
        if not isinstance(cards, list) or len(cards) > MAX_CARDS or len(native.canonical(cards)) > 1024 * 1024:
            raise ValueError(label + "卡片列表无效或过大")
        remaining = plan.get("authorDescription") or ""
        if not isinstance(remaining, str):
            raise ValueError(label + "说明需要是文字")
        for index, card in enumerate(cards):
            card_id = _card_id(plan_key, index, card)
            item = {"id": card_id, "plan": plan_key, "planLabel": label, "index": index,
                    "card": copy.deepcopy(card), "state": "pending", "description": "",
                    "pendingNextAction": "", "gameReady": False}
            if isinstance(card, dict) and isinstance(card.get("text"), str):
                remaining = remaining.replace(card["text"], "", 1)
            if card_id in applied:
                applied_card = applied[card_id]
                row_hash = applied_card["rowHash"]
                if (current_rows.get(plan_key, Counter())[row_hash]
                        >= required_rows.get(plan_key, Counter())[row_hash]):
                    item.update(state="applied", description=applied_card["description"],
                                pendingNextAction="对应条目仍在工程中；仍需游戏实战、形态与最终资源键核验。")
                else:
                    item["pendingNextAction"] = "这张卡曾经接入，但对应条目已被修改或删除，或当前定义仍有问题。历史与原卡保留，请接入方核对；不会自动重复追加或覆盖已有编辑。"
            elif (plan_key, index) in positions:
                item["pendingNextAction"] = "这张卡已接入后又有修改，旧条目仍保留。请先撤回上次接入，再预览新的卡片。"
            elif slot is None:
                item["pendingNextAction"] = "主动技能和强化弹射动作不能用被动词条代替。原说明、原动作和全部卡片保留，交接方需按真实动作定义实现。"
            elif blockers:
                item["pendingNextAction"] = "先由接入方处理真实定义缺口或原行问题，再预览此卡。"
            else:
                try:
                    row, kind, description = _generated_row(data, slot, card)
                    item.update(state="supported", description=description, row=row, kind=kind, slot=slot,
                                pendingNextAction="确认目标、单位、时间和单层规则后，明确选择才会追加；原条目仍保留。")
                except ValueError as error:
                    item["pendingNextAction"] = str(error)
            rows.append(item)
            item["detailPrompts"] = complex_rules.assistance_prompts(plan_key, card) if item["state"] == "pending" else []
        if remaining.strip():
            pending.append({"plan": plan_key, "planLabel": label, "text": remaining.strip(),
                            "pendingNextAction": "这段自由说明不会自动转换或删掉，请交接方逐项核对。"})
        reason = (plan.get("authorPolicy") or {}).get("reason") or ""
        if reason.strip():
            pending.append({"plan": plan_key, "planLabel": label, "text": reason,
                            "pendingNextAction": "协助申请继续保留，不能因部分卡片接入就标成完成。"})
    items = [{"id": item["id"], "plan": item["plan"], "planLabel": item["planLabel"],
              "text": (item["card"].get("text", "") if isinstance(item["card"].get("text", ""), str) else "卡片文字格式待核")
                      if isinstance(item["card"], dict) else "卡片格式待核对",
              "status": item["state"], "description": item["description"],
              "reason": item["pendingNextAction"], "detailPrompts": item["detailPrompts"]} for item in rows]
    from author_mechanics import build as mechanics_plan
    return {"schema": SCHEMA, "token": token, "revision": project.get("revision"),
            "integrationPlans": mechanics_plan(project, rows, pending, store),
            "cards": rows, "pending": pending, "blockers": blockers,
            "items": items, "notes": [catalog()["note"], catalog()["pendingNextAction"], complex_rules.CONDITION_NOTE],
            "canApply": not blockers and any(item["state"] == "supported" for item in rows),
            "canUndo": bool(history) and bool(data) and _hash(data) == history[-1]["afterHash"],
            "gameReady": False, "note": catalog()["note"]}


def apply(store, pid, revision, token, card_ids):
    """Explicitly append selected supported rows, serialize/read back, then save."""
    project = store.load(pid)
    if project["revision"] != revision:
        raise ValueError("工程已更新，请保存并重新预览")
    report = preview(project)
    if report["token"] != token:
        raise ValueError("玩法预览已过期，请重新预览后选择")
    if not isinstance(card_ids, list) or not card_ids or len(card_ids) > MAX_CARDS or any(not isinstance(key, str) for key in card_ids) or len(set(card_ids)) != len(card_ids):
        raise ValueError("请明确选择要接入的卡片")
    menu = {item["id"]: item for item in report["cards"]}
    if report["blockers"] or any(key not in menu or menu[key]["state"] != "supported" for key in card_ids):
        raise ValueError("只能接入本次预览中支持的卡片；未支持、已接入或缺定义的卡片继续保留")
    integration = copy.deepcopy(project.get("authorGameplayIntegration") or {"schema": SCHEMA, "history": []})
    if len(integration["history"]) >= MAX_HISTORY:
        raise ValueError("已保留十批撤回记录，请先撤回不需要的接入")
    data = project["nativeGameplay"]
    receipt = {"token": token, "beforeHash": _hash(data), "afterHash": "",
               "sourceHash": data["source"]["sha256"], "groups": {}, "cards": [],
               "readback": True, "gameReady": False}
    for card_id in card_ids:
        item = menu[card_id]
        # An earlier selection can create the first row of an empty ability
        # group. Recheck admission with those proposed rows before persisting
        # anything, so a main-only first row cannot hide a selected unison card.
        try:
            current_row, current_kind, _ = _generated_row(data, item["slot"], item["card"])
        except ValueError as error:
            raise ValueError("本批卡片的条件需要再核对，未保存任何接入：" + str(error)) from error
        if current_row != item["row"] or current_kind != item["kind"]:
            raise ValueError("本批卡片生成结果已变化，未保存任何接入，请重新预览")
        group, kind = native.group_for(data, item["slot"])
        receipt["groups"].setdefault(item["plan"], copy.deepcopy(group["rows"]))
        if len(group["rows"]) >= 128:
            raise ValueError(item["planLabel"] + "已达到条目上限")
        validate_row(kind, item["row"])
        group["rows"].append(copy.deepcopy(item["row"]))
        receipt["cards"].append({"id": card_id, "plan": item["plan"], "index": item["index"],
                                 "cardHash": _hash(item["card"]), "rowHash": _hash(item["row"]),
                                 "description": item["description"]})
    native.validate_native(data)
    # The genuine compressed native codec reads every generated row back. This
    # remains an isolated draft and allocates no real game resource keys.
    native.compile_native(data)
    receipt["afterHash"] = _hash(data)
    integration["history"].append(receipt)
    project["authorGameplayIntegration"] = integration
    validate(project)
    return store.save(project)


def undo(store, pid, revision):
    project = store.load(pid)
    if project["revision"] != revision:
        raise ValueError("工程已更新，请重新打开后撤回")
    validate(project)
    integration = copy.deepcopy(project.get("authorGameplayIntegration"))
    if not integration or not integration["history"]:
        raise ValueError("没有可撤回的作者玩法接入")
    receipt = integration["history"][-1]
    data = project.get("nativeGameplay")
    if not data or _hash(data) != receipt["afterHash"] or data["source"]["sha256"] != receipt["sourceHash"]:
        raise ValueError("已有词条在接入后被编辑，请保留当前修改并由接入方处理，不能自动覆盖")
    for plan, rows in receipt["groups"].items():
        slot = "leader" if plan == "leader" else int(plan[7:]) + 1
        group, _ = native.group_for(data, slot)
        group["rows"] = copy.deepcopy(rows)
    if _hash(data) != receipt["beforeHash"]:
        raise ValueError("撤回快照与原条目不一致，未保存")
    native.validate_native(data)
    native.compile_native(data)
    integration["history"].pop()
    project["authorGameplayIntegration"] = integration
    validate(project)
    return store.save(project)


def handoff(project, store=None):
    """JSON-safe author/maker summary, no raw rows or fabricated readiness."""
    report = preview(project, store=store)
    return {"schema": SCHEMA, "gameReady": False, "blockers": report["blockers"],
            "integrationPlans": report["integrationPlans"],
            "cards": [{key: value for key, value in item.items() if key not in ("row", "kind", "slot")}
                      for item in report["cards"]], "pending": report["pending"], "note": report["note"]}


def status(project):
    return handoff(project)
