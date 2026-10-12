"""Bounded author conditions and readable requests for unsupported mechanics.

Runtime evidence is recorded outside product code. The supported conditions are
native preconditions checked when an instant trigger arrives, never promises of
continuous reevaluation or a replacement active-skill program.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re

import native_gameplay as native

MAX_CONDITIONS = 2
_PERCENT = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(?:%|％)\Z")
_COUNT = re.compile(r"[0-9]+\Z")
_CONDITIONS = {
    "hp_at_least": ("自身游戏判定生命比例至少", "8", "HpHigh", "percent"),
    "hp_at_most": ("自身游戏判定生命比例至多", "9", "HpLow", "percent"),
    "combo_at_least": ("本次战斗连击至少", "10", "ComboHigh", "count"),
    "combo_at_most": ("本次战斗连击至多", "11", "ComboLow", "count"),
    "has_barrier": ("自身已有屏障", "87", "Barrier", "none"),
}
CONDITION_NOTE = "条件在触发时同时检查，之后变化不会自动撤销已给予的效果。生命比例沿用游戏判定（包括生命比例视作修正）；屏障条件只检查已有屏障。"

_DETAILS = {
    "active_skill": [("reference", "可以复用的技能或动作参考"), ("targets", "目标与作用范围"),
                     ("sequence", "动作、伤害、特效和声音的先后时点"), ("damage", "伤害类别、计算基准和段数"),
                     ("repeat", "再次施放、冷却和中断时怎样处理")],
    "summon": [("reference", "可以复用的召唤物参考"), ("appearance", "召唤物外观与动作素材"),
               ("count", "同时存在数量与重复召唤规则"), ("lifetime", "寿命、退场和跨阶段保留规则"),
               ("behavior", "移动、碰撞、攻击对象与伤害规则"), ("sequence", "出现、退场、特效和声音时点")],
    "skill_reuse": [("reference", "准备复用哪个现有技能或形态"), ("targets", "施放者与作用目标"),
                    ("repeat", "是否耗能、再次触发、次数与冷却规则"),
                    ("sequence", "动作结束、打断及恢复形态的时点")],
    "special": [("reference", "可以复用的角色、特殊动作或效果"),
                ("appearance", "变身或特殊状态的外观与动作"),
                ("sequence", "进入状态、触发效果和声音的时点"),
                ("behavior", "状态中能做什么，影响谁"),
                ("recovery", "结束、被打断和跨阶段时怎样恢复"),
                ("repeat", "重复进入、叠加与冷却规则")],
    "damage": [("damage", "技能、直接攻击或能力伤害及计算基准"), ("targets", "敌人选择、范围与段数"),
               ("element", "伤害属性与耐性规则"), ("sequence", "每段伤害、动作、特效与声音时点")],
    "custom": [("reference", "可以复用的现有角色、技能或素材"), ("behavior", "希望发生什么及作用对象"),
               ("sequence", "触发条件与发生时点"), ("repeat", "次数、持续、重复触发和结束规则")],
}


def catalog():
    return {"conditions": [{"id": key, "label": value[0], "valueUnit": value[3],
                            "valueHint": "0%至100%，例如80%" if value[3] == "percent" else
                            ("1至9999整数，例如20" if key == "combo_at_least" else "0至9999整数，例如20") if value[3] == "count" else "不需要数值"}
                           for key, value in _CONDITIONS.items()],
            "maxConditions": MAX_CONDITIONS, "conditionMode": "all_at_trigger", "conditionNote": CONDITION_NOTE,
            "assistanceDetails": [{"id": key, "fields": [{"id": field, "label": label} for field, label in fields]}
                                  for key, fields in _DETAILS.items()]}


def integer(value, minimum=0):
    if not isinstance(value, str) or len(value) > 12 or not _COUNT.fullmatch(value.strip()):
        raise ValueError("连击需要明确填写整数（例如20），不能把百分比、倍数或小数猜成次数")
    number = int(value.strip())
    if not minimum <= number <= 9999:
        raise ValueError("连击整数需在" + str(minimum) + "至9999之间")
    return number


def _percent(value):
    match = _PERCENT.fullmatch(value.strip()) if isinstance(value, str) and len(value) <= 120 else None
    if not match:
        raise ValueError("生命比例条件请写百分比，例如80%；不能猜测裸数字或倍数")
    try:
        number = Decimal(match[1])
        if not number.is_finite() or not 0 <= number <= 100:
            raise ValueError()
        native.scaled(number, 1000, "生命比例条件")
        return number
    except (InvalidOperation, ValueError):
        raise ValueError("生命比例条件需为0%至100%的可精确编码百分比")


def parse_conditions(card):
    values = card.get("conditions", [])
    if not isinstance(values, list) or len(values) > MAX_CONDITIONS:
        raise ValueError("最多填写两个同时满足的条件；更多条件或任一满足请保留说明并申请协助")
    if values and card.get("trigger") == "always":
        raise ValueError("持续生效与触发时检查不同；有条件卡片请选择具体触发，持续监听和撤销规则继续申请协助")
    result, seen, thresholds = [], set(), {}
    for condition in values:
        if not isinstance(condition, dict) or set(condition) != {"kind", "value"} or not isinstance(condition["kind"], str):
            raise ValueError("条件需要明确的种类与数值；目标、自定义比较或其他参数继续保留待协助")
        key = condition["kind"]
        spec = _CONDITIONS.get(key)
        if not spec:
            raise ValueError("这个条件尚未核实；请说明判断对象、阈值、比较方式与时点")
        if key in seen:
            raise ValueError("同一种条件重复填写，请整理为明确阈值或申请协助")
        seen.add(key)
        enum = native.composer.composer_meta()["enums"]["precondition"].get(spec[1])
        if not enum or enum.get("en") != spec[2]:
            raise ValueError("当前游戏条件定义与已核实语义不一致，需要制作方核对")
        if spec[3] == "percent":
            number = _percent(condition["value"])
            encoded = native.scaled(number, 1000, "生命比例条件")
            text = spec[0] + " " + str(number) + "%"
        elif spec[3] == "count":
            number = integer(condition["value"], minimum=1 if key == "combo_at_least" else 0)
            encoded = native.scaled(number, 100000, "连击条件")
            text = spec[0] + " " + str(number)
        else:
            if condition["value"] != "":
                raise ValueError("已有屏障条件不需要数值，也不能当作自动赋予屏障")
            number, encoded, text = None, "0", spec[0]
        thresholds[key] = number
        result.append({"kind": key, "enum": spec[1], "encoded": encoded, "description": text})
    for prefix in ("hp", "combo"):
        lower, upper = thresholds.get(prefix + "_at_least"), thresholds.get(prefix + "_at_most")
        if lower is not None and upper is not None and lower > upper:
            raise ValueError("上下限条件无法同时满足，请调整阈值或申请协助")
    return result


def write_conditions(row, kind, card, conditions):
    blocks = native.describe.layout(kind)["blocks"]
    start = 1 if card.get("mainOnly", False) else 0
    for offset, condition in enumerate(conditions, start=start):
        base = blocks["precondition" + str(offset + 1)]
        # kind, trigger-puller Myself, unused groups, level-independent
        # threshold pair, unused character groups and integer. Every used cell
        # is explicit and no inherited template target or threshold can leak.
        row[base:base + 7] = [condition["enum"], "0", "", condition["encoded"], condition["encoded"], "", "0"]


def assistance_prompts(plan, card):
    details = card.get("details") if isinstance(card, dict) else None
    details = details if isinstance(details, dict) else {}
    mechanic = details.get("mechanic")
    if not isinstance(mechanic, str) or mechanic not in _DETAILS:
        mechanic = "active_skill" if plan in ("activeSkill", "pf") else "damage" if isinstance(card, dict) and card.get("effect") == "damage" else "custom"
    result = []
    for key, label in _DETAILS[mechanic]:
        value = details.get(key, "")
        result.append({"field": key, "label": label,
                       "value": value if isinstance(value, str) else "",
                       "status": "provided" if isinstance(value, str) and value.strip() else "needed"})
    known = {key for key, _ in _DETAILS[mechanic]} | {"mechanic", "referenceChoice", "referenceDigest"}
    for key, value in details.items():
        if isinstance(key, str) and key not in known and isinstance(value, str) and value.strip():
            result.append({"field": key, "label": "保留的其它要求（" + key + "）", "value": value,
                           "status": "provided"})
    return result


def check_details(card):
    if "details" not in card:
        return
    details = card["details"]
    if not isinstance(details, dict) or len(details) > 16 or any(not isinstance(key, str) or not isinstance(value, str) or len(value) > 4000 for key, value in details.items()):
        raise ValueError("特殊机制补充需要是可读文字，各项内容继续保留待核")
    if any(value.strip() for value in details.values()):
        raise ValueError("已填写特殊机制要求，需要按补充说明继续协助；不会只套用基础选项而遗漏这些要求")
