"""Artist-facing action slots; empty presets contain no invented game artwork."""
from __future__ import annotations

import copy
import math
import uuid


ACTION_PRESETS = [
    {"slot": "neutral", "name": "待机", "purpose": "角色平时停留时的动作，也是检查整体造型的起点。", "kind": "loop", "variant": "normal", "default": True, "aliases": ["idle", "待机", "站立"]},
    {"slot": "walk_front", "name": "向前移动", "purpose": "向前移动时播放；客户端按半速播放这一槽位。", "kind": "loop", "variant": "normal", "runtimeSpeed": .5, "default": True, "aliases": ["walk", "forward", "前进", "向前", "向前移动"]},
    {"slot": "walk_back", "name": "向后移动", "purpose": "向后移动时播放；客户端按半速播放这一槽位。", "kind": "loop", "variant": "normal", "runtimeSpeed": .5, "default": True, "aliases": ["back", "backward", "后退", "向后", "向后移动"]},
    {"slot": "skill_ready", "name": "技能准备", "purpose": "准备释放技能时的角色姿势，按官方槽位播放一次。技能中的额外动作可单独添加。", "kind": "once", "variant": "normal", "default": True, "aliases": ["skill", "cast", "施法", "技能准备", "技能"]},
    {"slot": "kachidoki", "name": "胜利", "purpose": "胜利时的庆祝动作。", "kind": "loop", "variant": "normal", "default": True, "aliases": ["victory", "win", "胜利"]},
    {"slot": "into_coffin", "name": "倒下", "purpose": "失去战斗能力时，角色进入倒下状态的过程。播放后由游戏切换状态。", "kind": "pass", "variant": "normal", "default": True, "aliases": ["defeat", "down", "die", "倒下", "战败"]},
    {"slot": "ghost_raise", "name": "灵魂出现", "purpose": "失去战斗能力后，灵魂出现的过渡动作。播放后由游戏切换状态。", "kind": "pass", "variant": "normal", "default": True, "aliases": ["灵魂出现"]},
    {"slot": "ghost_neutral", "name": "灵魂待机", "purpose": "等待复活时的灵魂循环动作。", "kind": "loop", "variant": "normal", "default": True, "aliases": ["ghost", "灵魂待机"]},
    {"slot": "revive", "name": "复活", "purpose": "复活回到战斗时的过渡动作。", "kind": "once", "variant": "normal", "default": True, "aliases": ["revival", "复活"]},
    {"slot": "special_land", "name": "获取·登场", "purpose": "获得角色时的登场动作，播放后由游戏切换展示状态，放在特殊动作组中。", "kind": "pass", "variant": "special", "default": True, "aliases": ["intro", "entrance", "登场"]},
    {"slot": "special_pose", "name": "获取·定格", "purpose": "登场后的展示姿势，按官方槽位播放一次后停在末帧。", "kind": "once", "variant": "special", "default": True, "aliases": ["pose", "定格"]},
    {"slot": "attack_initial", "name": "攻击·起手", "purpose": "部分角色的攻击起手动作；播放后由游戏切换状态，按设计需要添加。", "kind": "pass", "variant": "normal", "default": False, "aliases": ["attack_start", "攻击起手"]},
    {"slot": "attack_charge", "name": "攻击·蓄力", "purpose": "部分角色的攻击蓄力动作；按设计需要添加。", "kind": "loop", "variant": "normal", "default": False, "aliases": ["charge", "蓄力"]},
    {"slot": "attack_action", "name": "攻击·动作", "purpose": "部分角色的攻击主体动作；播放后由游戏切换状态，按设计需要添加。", "kind": "pass", "variant": "normal", "default": False, "aliases": ["attack", "攻击动作"]},
    {"slot": "attack_fire", "name": "攻击·释放", "purpose": "部分角色的攻击释放动作；按设计需要添加。", "kind": "once", "variant": "normal", "default": False, "aliases": ["attack_release", "攻击释放"]},
    {"slot": "wince_ready", "name": "受击准备", "purpose": "少数官方角色提供的受击状态姿势，并非所有角色都需要。", "kind": "stop", "variant": "normal", "default": False, "aliases": ["hit", "受击", "受击准备"]},
    {"slot": "stun_ready", "name": "眩晕准备", "purpose": "少数官方角色提供的眩晕状态姿势，并非所有角色都需要。", "kind": "stop", "variant": "normal", "default": False, "aliases": ["stun", "眩晕", "眩晕准备"]},
    {"slot": "dead", "name": "死亡姿势", "purpose": "少数官方角色的特殊死亡状态；常规角色倒下使用“倒下”槽位。", "kind": "stop", "variant": "normal", "default": False, "aliases": ["死亡"]},
]


def preset_animation(preset):
    return {"id": uuid.uuid4().hex[:12], "name": preset["name"], "slot": preset["slot"],
            "variant": preset["variant"], "kind": preset["kind"], "fps": 60,
            "runtimeSpeed": preset.get("runtimeSpeed", 1), "frameScale": 6,
            "clips": [], "preset": preset["slot"], "purpose": preset["purpose"]}


def default_animations():
    return [preset_animation(p) for p in ACTION_PRESETS if p["default"]]


def catalog():
    return copy.deepcopy(ACTION_PRESETS)


def default_action_contract(animation=None):
    """Author intent and native selector verification are independent declarations."""
    return {"schemaVersion": 1, "purpose": "", "sourceFrames": [], "sourceCanvas": None,
            "bodyAnchor": None, "feetAnchor": None, "durationTicks": None, "loop": None,
            "returnState": "", "selector": {"status": "unknown", "value": None,
            "context": "", "evidence": ""}}


def normalize_action_contract(animation):
    result = default_action_contract()
    if "actionContract" not in animation:
        return result
    declared = animation["actionContract"]
    if not isinstance(declared, dict):
        raise ValueError("动作契约必须为对象")
    result.update(copy.deepcopy(declared))
    if result["schemaVersion"] != 1 or isinstance(result["schemaVersion"], bool):
        raise ValueError("不支持此动作契约版本")
    for key in ("purpose", "returnState"):
        if not isinstance(result[key], str):
            raise ValueError("动作用途和返回状态必须为文本")
    for key in ("sourceCanvas", "bodyAnchor", "feetAnchor"):
        pair = result[key]
        if pair is not None and (not isinstance(pair, list) or len(pair) != 2 or not all(
                isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in pair)):
            raise ValueError("动作画布和锚点必须为两个有限数值或未标注")
        if key == "sourceCanvas" and pair is not None and min(pair) <= 0:
            raise ValueError("动作源画布必须大于零")
    duration = result["durationTicks"]
    if duration is not None and (not isinstance(duration, int) or isinstance(duration, bool) or duration < 1):
        raise ValueError("动作时长必须为正整数播放帧或未标注")
    if result["loop"] is not None and not isinstance(result["loop"], bool):
        raise ValueError("动作循环必须为布尔值或未标注")
    if not isinstance(result["sourceFrames"], list) or not all(isinstance(row, dict) for row in result["sourceFrames"]):
        raise ValueError("动作源帧必须为引用数组")
    for row in result["sourceFrames"]:
        if not isinstance(row.get("source"), str) or not row["source"]:
            raise ValueError("动作源帧必须引用原稿编号")
        if row.get("cell") is not None and (not isinstance(row["cell"], int) or isinstance(row["cell"], bool) or row["cell"] < 0):
            raise ValueError("动作源格号必须从 0 开始")
    selector = result["selector"]
    if not isinstance(selector, dict):
        raise ValueError("原生 selector 必须为对象")
    selector = {**default_action_contract()["selector"], **selector}
    if selector["status"] not in ("unknown", "declared", "verified", "not_applicable"):
        raise ValueError("原生 selector 核验状态无效")
    if selector["value"] is not None and (not isinstance(selector["value"], (int, str)) or isinstance(selector["value"], bool)):
        raise ValueError("原生 selector 值无效")
    for key in ("context", "evidence"):
        if not isinstance(selector[key], str):
            raise ValueError("原生 selector 语境和证据必须为文本")
    if selector["status"] == "verified" and (selector["value"] is None or not selector["context"].strip() or not selector["evidence"].strip()):
        raise ValueError("已核验 selector 必须有值、调用语境和证据")
    if selector["status"] == "unknown" and selector["value"] is not None:
        raise ValueError("待核 selector 不能声明已知值；可使用作者声明状态")
    result["selector"] = selector
    return result


def validate_action_contracts(project):
    from source_intake import validate_source_intake
    intake = validate_source_intake(project)
    sources = {row["id"] for row in intake["sources"]}
    for animation in project.get("animations", []):
        contract = normalize_action_contract(animation)
        for row in contract["sourceFrames"]:
            if row["source"] not in sources:
                raise ValueError("动作契约引用的原稿不存在")
        for clip in animation.get("clips", []):
            if "sourceRef" not in clip:
                continue
            ref = clip["sourceRef"]
            if not isinstance(ref, dict):
                raise ValueError("动作帧原稿引用必须为对象")
            # Reuse provenance checks on a copy; reads never add a derivative.
            candidate = {"assets": project.get("assets", {}), "sourceIntake": {**intake, "derivatives": [
                {"asset": clip.get("asset"), "source": ref.get("source"), "cell": ref.get("cell"),
                 "rect": ref.get("rect"), "mask": ref.get("mask"), "transform": ref.get("transform")} ]}}
            validate_source_intake(candidate)
    return True


def action_contract_payload(project):
    validate_action_contracts(project)
    return [{"id": a["id"], "slot": a.get("slot"), "variant": a.get("variant", "normal"),
             "annotated": "actionContract" in a, "contract": normalize_action_contract(a),
             "frameMapping": [{"index": i, "asset": c.get("asset"), "hold": c.get("hold"),
                               "sourceRef": copy.deepcopy(c.get("sourceRef"))}
                              for i, c in enumerate(a.get("clips", []))]}
            for a in project.get("animations", [])]
