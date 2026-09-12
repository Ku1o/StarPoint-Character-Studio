"""Artist-facing action slots; empty presets contain no invented game artwork."""
from __future__ import annotations

import copy
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
