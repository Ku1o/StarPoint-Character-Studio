"""Artist-facing production brief and maker handoff checks.

The existing project schema and MOD gameplay fields remain authoritative for
backward compatibility.  ``productionBrief`` is an additive, text-first layer
for a character's author, asset supplier and implementation handoff.  It never
pretends that a file, a native mechanic or a practice-battle result exists.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

SCHEMA = "starpoint-character-production-brief-v1"
VERSION = 1

WORKFLOW_STAGES = (
    ("author_package", "作者填写包", "作者完成文字设定、资源说明和语音清单"),
    ("maker_review", "制作方核验", "制作方确认原生机制、尺寸、编码和待核实项"),
    ("asset_production", "资源制作", "逐项制作并回填立绘、动作、特效、图标和声音"),
    ("data_implementation", "数据 / DSL 实现", "接入方转换能力、技能与资源绑定"),
    ("practice_battle", "本地练习战验收", "只在练习战验证，覆盖自动战斗与目标阵容"),
    ("release_handoff", "发布整合", "完成资源、数据、版本链和回退记录后交付"),
)
WORKFLOW_STATUS = {key for key, _, _ in WORKFLOW_STAGES}
ITEM_STATUS = ("missing", "provided", "reuse_official", "needs_review", "not_applicable")
VOICE_SOURCE = ("new_recording", "reuse_official", "to_generate", "not_applicable")
NATIVE_SUPPORT = ("native_supported", "client_adaptation", "needs_verification", "unknown")


def _text(value="", limit=12000):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"文本必须是 {limit} 字以内")
    return value


def _bool(value, label):
    if not isinstance(value, bool):
        raise ValueError(label + "必须是开关值")
    return value


def _choice(value, choices, label):
    if value not in choices:
        raise ValueError(label + "的值无效")
    return value


def _plan(label=""):
    return {
        "name": "",
        "authorDescription": "",
        "trigger": "",
        "target": "",
        "range": "",
        "hits": "",
        "multiplier": "",
        "duration": "",
        "cooldown": "",
        "statusIcon": "",
        "nativeSupport": "unknown",
        "nativeConstraints": "",
        "verificationItems": "",
        "previewReference": "",
        "makerNotes": "",
        "label": label,
    }


def _resource(key, label, group, *, required=True, form="both", expected="", frame_hint=""):
    return {
        "id": key,
        "label": label,
        "group": group,
        "required": required,
        "form": form,
        "status": "missing",
        "source": "new",
        "assetIds": [],
        "expectedSize": expected,
        "displaySize": "",
        "frameCount": "",
        "atlasSize": "",
        "compression": "",
        "simultaneousBudget": "",
        "transparentBackground": "",
        "frameHint": frame_hint,
        "notes": "",
    }


def _voice(key, label, usage, *, form="single", required=True, pair=None):
    return {
        "id": key,
        "label": label,
        "usage": usage,
        "form": form,
        "pairId": pair or (key if form == "pair" else ""),
        "required": required,
        "status": "missing",
        "source": "new_recording",
        "textJapanese": "",
        "dialect": "",
        "toneReference": "",
        "volume": "",
        "duration": "",
        "filename": "",
        "encoding": "",
        "assetId": "",
        "notes": "",
    }


def default_review_items():
    return [
        {"id": "official_projectile", "label": "官方弹道优先复用后改色", "state": "unreviewed", "note": "优先复用可辨识的官方弹道，再做颜色或尺寸调整。"},
        {"id": "pf_decoration", "label": "PF 装饰保持辨识度", "state": "unreviewed", "note": "避免高速弹珠周边难以辨认的小月光装饰。"},
        {"id": "native_entry", "label": "能力 / 直击 / PF / 技能伤害入口", "state": "unreviewed", "note": "标明原生支持、需客户端适配或待核实。"},
        {"id": "preview_boundary", "label": "技能预览不等于实战", "state": "unreviewed", "note": "预览通过后仍需练习战验证。"},
        {"id": "practice_battle", "label": "练习战覆盖自动战斗和目标阵容", "state": "unreviewed", "note": "退出练习战后检查活动记录和 H400 恢复。"},
        {"id": "form_pair", "label": "进化前后资源和语音成对", "state": "unreviewed", "note": "缺失进化前语音可能触发 C8105。"},
        {"id": "audio_container", "label": "校验游戏所需音频封装", "state": "unreviewed", "note": "普通 MP3 放入 CDN 不代表客户端可播放。"},
        {"id": "portrait_blank", "label": "立绘 / 插画无空白或错误裁切", "state": "unreviewed", "note": "检查详情图尺寸、透明背景和实际显示尺寸。"},
        {"id": "pixel_visibility", "label": "像素腿和白背景可见", "state": "unreviewed", "note": "避免颜色或白底导致像素角色局部不可见。"},
        {"id": "status_icon", "label": "状态图标背景与月行图标", "state": "unreviewed", "note": "黑底违和、月行独立图标需要单独确认。"},
        {"id": "native_chart", "label": "官方图表化描述未被破坏", "state": "unreviewed", "note": "保留官方字段与图表表达，技术编辑另记在核验区。"},
        {"id": "buff_duration", "label": "隐藏增益和强化时长限制", "state": "unreviewed", "note": "确认原生机制能否支持隐藏增益、强化时长和刷新。"},
        {"id": "pf_reset", "label": "PF 延长和重置行为", "state": "unreviewed", "note": "明确延长、重置、叠加还是重新计时。"},
        {"id": "hit_effect", "label": "弹道与命中特效可区分", "state": "unreviewed", "note": "命中特效要有足够辨识度，不能与弹道混淆。"},
        {"id": "environment_chain", "label": "本地 CDN 与正式云服版本链分开", "state": "unreviewed", "note": "本地高版本 CDN 和正式云服 1.4.115 分开记录。"},
        {"id": "save_error", "label": "错误存档与 C3212 区分", "state": "unreviewed", "note": "记录存档错误与客户端 C3212 的独立复现证据。"},
    ]


def default_production_brief():
    plans = {key: _plan(label) for key, label in (
        ("activeSkill", "主动技能"), ("pf", "PF"), ("leader", "队长技"),
    )}
    plans["abilities"] = [_plan(f"能力 {slot}") | {"slot": slot} for slot in range(1, 7)]
    resources = [
        _resource("portrait_base", "进化前大立绘", "portrait", form="base", expected="1440×1920"),
        _resource("portrait_evolved", "进化后大立绘", "portrait", form="evolved", expected="1440×1920"),
        _resource("detail_base", "进化前详情 / 缩略图", "ui", form="base", expected="按官方槽位"),
        _resource("detail_evolved", "进化后详情 / 缩略图", "ui", form="evolved", expected="按官方槽位"),
        _resource("pixel_idle", "像素小人：待机", "pixel", frame_hint="逐帧 PNG，画布和定位点一致"),
        _resource("pixel_move", "像素小人：前进 / 后退", "pixel", frame_hint="逐帧 PNG，检查腿部对比度"),
        _resource("pixel_attack", "像素小人：攻击 / 受击 / 倒下", "pixel", frame_hint="逐帧 PNG，可由模板复制后调整"),
        _resource("pixel_special", "像素小人：获取 / 登场 / 复活", "pixel", required=False, frame_hint="特殊动作按实际需要提供"),
        _resource("skill_projectile", "主动技能：弹道帧集", "skill", frame_hint="弹道、飞行、消失分别标记"),
        _resource("skill_hit", "主动技能：命中帧集", "skill", frame_hint="命中特效需能与弹道区分"),
        _resource("skill_fullscreen", "主动技能：全屏 / 镜头帧集", "skill", required=False),
        _resource("pf_frames", "PF：起手 / 飞行 / 命中帧集", "pf", frame_hint="PF 的延长和重置单独记录"),
        _resource("skill_icons", "技能图标与技能栏图", "icon", expected="按官方图集槽位"),
        _resource("status_icons", "状态图标", "icon", required=False, expected="透明 PNG，避免黑底"),
        _resource("atlas_skill", "技能图集与帧索引", "atlas", frame_hint="记录图集尺寸、压缩和同时在场预算"),
        _resource("atlas_pf", "PF 图集与帧索引", "atlas", required=False),
    ]
    voices = [
        _voice("home_base", "主城语音（进化前）", "home", form="base", pair="home"),
        _voice("home_evolved", "主城语音（进化后）", "home", form="evolved", pair="home"),
        _voice("acquisition", "角色获取", "acquisition"),
        _voice("detail", "角色详情", "detail"),
        _voice("enhancement", "强化", "enhancement"),
        _voice("evolution", "进化", "evolution"),
        _voice("battle_start", "战斗开始", "battle_start"),
        _voice("skill", "释放技能", "skill"),
        _voice("pf", "PF", "pf"),
        _voice("victory", "胜利", "victory"),
        _voice("defeat", "失败", "defeat", required=False),
        _voice("damage", "受击", "damage", required=False),
        _voice("down", "倒下 / 复活", "down", required=False),
    ]
    sounds = [
        _voice("skill_sfx", "技能施放音效", "skill_sfx"),
        _voice("hit_sfx", "技能命中音效", "hit_sfx"),
        _voice("pf_sfx", "PF 音效", "pf_sfx", required=False),
        _voice("charge_sfx", "蓄力音效", "charge_sfx", required=False),
    ]
    handoff = [{"id": key, "label": label, "complete": False, "note": ""} for key, label, _ in WORKFLOW_STAGES]
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "workflow": {"status": "author_package", "statusNote": "", "handoff": handoff},
        "author": {
            "characterName": "", "title": "", "element": "火", "role": "", "race": "",
            "baseForm": "", "evolvedForm": "", "characterIdReserved": "", "resourceIdReserved": "",
            "growth": "", "trainingCost": "", "leaderPosition": "", "memberPosition": "",
        },
        "plans": plans,
        "resources": resources,
        "voices": voices,
        "sounds": sounds,
        "review": default_review_items(),
        "acceptance": {
            "previewIsNotCombat": True,
            "practiceBattleStatus": "not_run",
            "automaticBattle": False,
            "targetParty": "",
            "activityRecovery": "",
            "localCdnVersion": "",
            "cloudReleaseVersion": "1.4.115",
            "notes": "",
        },
        "notes": "",
    }


def _merge_record(default, supplied):
    if not isinstance(supplied, dict):
        raise ValueError("制作记录必须是对象")
    result = copy.deepcopy(default)
    result.update(copy.deepcopy(supplied))
    return result


def normalize_production_brief(project_or_brief):
    """Return a validated brief while preserving unknown future fields."""
    is_project = isinstance(project_or_brief, dict) and (
        project_or_brief.get("schema") == "starpoint-character-studio-v1"
        or "productionBrief" in project_or_brief
        or ("id" in project_or_brief and ("assets" in project_or_brief or "identity" in project_or_brief))
    )
    supplied = project_or_brief.get("productionBrief", {}) if is_project else project_or_brief
    legacy_project = is_project and not project_or_brief.get("productionBrief")
    if supplied in (None, {}):
        supplied = {}
    if not isinstance(supplied, dict):
        raise ValueError("制作填写包必须是对象")
    if supplied.get("schema", SCHEMA) != SCHEMA:
        raise ValueError("制作填写包版本不受支持")
    base = default_production_brief()
    result = copy.deepcopy(base)
    result.update(copy.deepcopy(supplied))
    result["schema"] = SCHEMA
    result["version"] = VERSION

    workflow = _merge_record(base["workflow"], supplied.get("workflow", {}))
    workflow["status"] = _choice(workflow.get("status"), WORKFLOW_STATUS, "制作状态")
    workflow["statusNote"] = _text(workflow.get("statusNote", ""), 4000)
    handoff = {row["id"]: row for row in base["workflow"]["handoff"]}
    supplied_handoff = workflow.get("handoff", [])
    if not isinstance(supplied_handoff, list):
        raise ValueError("交接清单必须是数组")
    for row in supplied_handoff:
        if not isinstance(row, dict) or row.get("id") not in handoff:
            raise ValueError("交接清单项目无效")
        item = handoff[row["id"]]
        item.update(row)
        item["complete"] = _bool(item.get("complete"), "交接完成状态")
        item["note"] = _text(item.get("note", ""), 4000)
    workflow["handoff"] = list(handoff.values())
    result["workflow"] = workflow

    author = _merge_record(base["author"], supplied.get("author", {}))
    for key in base["author"]:
        author[key] = _text(author.get(key, ""), 2000)
    result["author"] = author

    plans = copy.deepcopy(base["plans"])
    supplied_plans = supplied.get("plans", {})
    if not isinstance(supplied_plans, dict):
        raise ValueError("能力填写项必须是对象")
    for key in ("activeSkill", "pf", "leader"):
        plans[key] = _merge_record(plans[key], supplied_plans.get(key, {}))
        plans[key]["nativeSupport"] = _choice(plans[key].get("nativeSupport"), NATIVE_SUPPORT, "原生机制支持")
        for field in base["plans"][key]:
            if field != "nativeSupport":
                plans[key][field] = _text(plans[key][field], 12000)
    abilities = supplied_plans.get("abilities", [])
    if not isinstance(abilities, list):
        raise ValueError("能力 1-6 必须是数组")
    supplied_by_slot = {}
    for item in abilities:
        if not isinstance(item, dict) or type(item.get("slot")) is not int or not 1 <= item["slot"] <= 6:
            raise ValueError("能力槽位必须是 1 至 6")
        if item["slot"] in supplied_by_slot:
            raise ValueError("能力槽位不能重复")
        supplied_by_slot[item["slot"]] = item
    plans["abilities"] = []
    for slot in range(1, 7):
        item = _merge_record(base["plans"]["abilities"][slot - 1], supplied_by_slot.get(slot, {}))
        item["slot"] = slot
        item["nativeSupport"] = _choice(item.get("nativeSupport"), NATIVE_SUPPORT, "原生机制支持")
        for field in base["plans"]["abilities"][slot - 1]:
            if field not in ("slot", "nativeSupport"):
                item[field] = _text(item[field], 12000)
        plans["abilities"].append(item)
    result["plans"] = plans

    # Old projects keep their original fields as the source of truth.  Seed
    # the new author-facing layer only when it did not exist; never overwrite
    # an explicit production brief or change the legacy gameplay object.
    if legacy_project:
        identity = project_or_brief.get("identity", {})
        if isinstance(identity, dict):
            author = result["author"]
            for target, source in (("title", "title"), ("element", "element"), ("role", "role"), ("race", "race")):
                value = identity.get(source)
                if isinstance(value, str) and value and not author[target]:
                    author[target] = value
        template = project_or_brief.get("template", {})
        name = template.get("name") if isinstance(template, dict) else None
        name = name or project_or_brief.get("name")
        if isinstance(name, str) and name:
            result["author"]["characterName"] = name
        legacy_skill = project_or_brief.get("skill", {})
        if isinstance(legacy_skill, dict):
            active = result["plans"]["activeSkill"]
            if isinstance(legacy_skill.get("name"), str):
                active["name"] = legacy_skill["name"]
            if isinstance(legacy_skill.get("description"), str):
                active["authorDescription"] = legacy_skill["description"]
        legacy_gameplay = project_or_brief.get("gameplay", {})
        if isinstance(legacy_gameplay, dict):
            leader = legacy_gameplay.get("leader", {})
            if isinstance(leader, dict):
                result["plans"]["leader"]["name"] = leader.get("name", "") if isinstance(leader.get("name", ""), str) else ""
                result["plans"]["leader"]["authorDescription"] = leader.get("description", "") if isinstance(leader.get("description", ""), str) else ""
            abilities = legacy_gameplay.get("abilities", [])
            if isinstance(abilities, list):
                for old in abilities:
                    if not isinstance(old, dict) or type(old.get("slot")) is not int or not 1 <= old["slot"] <= 6:
                        continue
                    target = result["plans"]["abilities"][old["slot"] - 1]
                    if isinstance(old.get("name"), str):
                        target["name"] = old["name"]
                    if isinstance(old.get("description"), str):
                        target["authorDescription"] = old["description"]

    def normalize_list(key, defaults, label):
        values = supplied.get(key, [])
        if not isinstance(values, list):
            raise ValueError(label + "必须是数组")
        by_id = {item["id"]: copy.deepcopy(item) for item in defaults}
        order = [item["id"] for item in defaults]
        for item in values:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] not in by_id:
                raise ValueError(label + "项目标识无效")
            by_id[item["id"]].update(copy.deepcopy(item))
        return [by_id[key] for key in order]

    resources = normalize_list("resources", base["resources"], "资源清单")
    for item in resources:
        item["status"] = _choice(item.get("status"), ITEM_STATUS, "资源状态")
        item["source"] = _text(item.get("source", ""), 200)
        if not isinstance(item.get("assetIds"), list) or len(item["assetIds"]) > 100:
            raise ValueError("资源关联素材必须是数组")
        item["assetIds"] = [_text(x, 100) for x in item["assetIds"]]
        for key, limit in (("notes", 8000), ("expectedSize", 200), ("displaySize", 200), ("frameCount", 100), ("atlasSize", 100), ("compression", 200), ("simultaneousBudget", 200), ("transparentBackground", 200)):
            item[key] = _text(item.get(key, ""), limit)
    result["resources"] = resources

    voices = normalize_list("voices", base["voices"], "语音清单")
    sounds = normalize_list("sounds", base["sounds"], "音效清单")
    for item in voices + sounds:
        item["status"] = _choice(item.get("status"), ITEM_STATUS, "语音状态")
        item["source"] = _choice(item.get("source"), VOICE_SOURCE, "语音来源")
        for key, limit in (("textJapanese", 4000), ("dialect", 500), ("toneReference", 1000), ("volume", 100), ("duration", 100), ("filename", 260), ("encoding", 300), ("assetId", 100), ("notes", 8000)):
            item[key] = _text(item.get(key, ""), limit)
    result["voices"] = voices
    result["sounds"] = sounds

    review = normalize_list("review", base["review"], "稳定经验检查项")
    for item in review:
        item["state"] = _choice(item.get("state", "unreviewed"), ("unreviewed", "pass", "risk", "not_applicable"), "检查项状态")
        item["note"] = _text(item.get("note", ""), 4000)
    result["review"] = review

    acceptance = _merge_record(base["acceptance"], supplied.get("acceptance", {}))
    acceptance["previewIsNotCombat"] = _bool(acceptance.get("previewIsNotCombat"), "预览边界")
    acceptance["automaticBattle"] = _bool(acceptance.get("automaticBattle"), "自动战斗验收")
    acceptance["practiceBattleStatus"] = _choice(acceptance.get("practiceBattleStatus"), ("not_run", "passed", "failed", "blocked"), "练习战状态")
    for key in ("targetParty", "activityRecovery", "localCdnVersion", "cloudReleaseVersion", "notes"):
        acceptance[key] = _text(acceptance.get(key, ""), 4000)
    result["acceptance"] = acceptance
    result["notes"] = _text(result.get("notes", ""), 12000)
    json.dumps(result, ensure_ascii=False, allow_nan=False)
    return result


def attach(project):
    """Normalize the additive brief in memory for a loaded project."""
    result = copy.deepcopy(project)
    result["productionBrief"] = normalize_production_brief(result)
    return result["productionBrief"]


def hydrate_from_project(project):
    """Reflect imported project assets in the checklist without guessing support.

    The function only marks a row when a corresponding source asset is present.
    A complex effect is deliberately marked ``needs_review``: its existence is
    useful to the maker, but does not prove projectile/hit/PF classification or
    game compatibility.
    """
    brief = normalize_production_brief(project)
    assets = project.get("assets", {}) if isinstance(project.get("assets"), dict) else {}
    by_id = {item["id"]: item for item in brief["resources"]}
    voices_by_id = {item["id"]: item for item in brief["voices"]}
    sounds_by_id = {item["id"]: item for item in brief["sounds"]}
    identity = project.get("identity", {}) if isinstance(project.get("identity"), dict) else {}
    author = brief["author"]
    template = project.get("template", {}) if isinstance(project.get("template"), dict) else {}
    character_name = template.get("name") or identity.get("name") or project.get("name", "")
    if isinstance(character_name, str) and character_name and not author["characterName"]:
        author["characterName"] = character_name
    for target, source in (("title", "title"), ("element", "element"), ("role", "role"), ("race", "race")):
        value = identity.get(source)
        if isinstance(value, str) and value and not author[target]:
            author[target] = value

    def existing(values):
        result = []
        for value in values:
            if isinstance(value, str) and value in assets and value not in result:
                result.append(value)
        return result

    def mark(resource_id, values, status="provided", note=""):
        ids = existing(values)
        if not ids:
            return
        item = by_id[resource_id]
        item["status"] = status
        item["assetIds"] = ids
        if note and not item.get("notes"):
            item["notes"] = note

    def mark_voice(voice_id, values, status="provided"):
        ids = existing(values)
        if not ids:
            return
        item = voices_by_id[voice_id]
        item["status"] = status
        item["source"] = "reuse_official"
        item["assetId"] = ids[0]

    portraits = project.get("portraits", {}) if isinstance(project.get("portraits"), dict) else {}
    mark("portrait_base", [portraits.get("base")])
    mark("portrait_evolved", [portraits.get("evolved")])
    ui_sources = project.get("uiSources", {}) if isinstance(project.get("uiSources"), dict) else {}
    for form, resource_id in (("base", "detail_base"), ("evolved", "detail_evolved")):
        mark(resource_id, [value for key, value in ui_sources.items() if str(key).startswith(form + ":")])
    animations = project.get("animations", []) if isinstance(project.get("animations"), list) else []
    def animation_assets(slots):
        values = []
        for animation in animations:
            if animation.get("slot") not in slots:
                continue
            values.extend(clip.get("asset") for clip in animation.get("clips", []) if isinstance(clip, dict))
            for frame in animation.get("nativeFrames", []):
                values.extend(command.get("asset") for command in frame if isinstance(command, dict))
        return values
    mark("pixel_idle", animation_assets({"neutral", "ghost_neutral"}))
    mark("pixel_move", animation_assets({"walk_front", "walk_back"}))
    mark("pixel_attack", animation_assets({"attack_initial", "attack_charge", "attack_finish", "into_coffin", "kachidoki"}))
    mark("pixel_special", animation_assets({"special_land", "special_pose", "revive", "ghost_raise"}))
    effects = project.get("effects", []) if isinstance(project.get("effects"), list) else []
    effect_assets = []
    for effect in effects:
        effect_assets.extend(clip.get("asset") for clip in effect.get("clips", []) if isinstance(clip, dict))
        for frame in effect.get("nativeFrames", []):
            effect_assets.extend(command.get("asset") for command in frame if isinstance(command, dict))
    if existing(effect_assets):
        note = f"已导入 {len(effects)} 个特效，需制作方继续区分弹道、命中和 PF 用途。"
        for resource_id in ("skill_projectile", "skill_hit", "pf_frames"):
            mark(resource_id, effect_assets, "needs_review", note)
    mark("skill_icons", [value for key, value in ui_sources.items() if "skill" in str(key) or "battle_control_board" in str(key)])
    references = project.get("referenceFiles", []) if isinstance(project.get("referenceFiles"), list) else []
    atlas_files = [name for name in references if isinstance(name, str) and name.endswith(".atlas.json")]
    effect_atlas_files = [name for name in atlas_files if name.startswith("effect/")]
    if effect_atlas_files:
        item = by_id["atlas_skill"]
        if item["status"] == "missing":
            item["status"] = "provided"
            item["notes"] = f"参考包已包含 {len(effect_atlas_files)} 个特效图集索引，需结合实际编译产物回读。"

    voices = project.get("voices", []) if isinstance(project.get("voices"), list) else []
    voice_map = {"acquisition": {"join"}, "evolution": {"evolution"}, "battle_start": {"battle_start"},
                 "skill": {"skill_voice"}, "pf": {"power_flip"}, "victory": {"win"}, "down": {"outhole"}}
    for resource_id, usages in voice_map.items():
        mark_voice(resource_id, [voice.get("asset") for voice in voices if voice.get("usage") in usages])
    home = [voice.get("asset") for voice in voices if voice.get("usage") == "home"]
    mark_voice("home_base", home[:1])
    mark_voice("home_evolved", home[1:2])
    sounds = project.get("sounds", []) if isinstance(project.get("sounds"), list) else []
    for sound_id, usages in (("skill_sfx", {"skill_sfx"}), ("hit_sfx", {"hit_sfx"}),
                             ("pf_sfx", {"power_flip_sfx"}), ("charge_sfx", {"charge_sfx"})):
        ids = existing(sound.get("asset") for sound in sounds if sound.get("usage") in usages)
        if ids:
            item = sounds_by_id[sound_id]
            item.update(status="provided", source="reuse_official", assetId=ids[0])
    project["productionBrief"] = brief
    return brief


def _record_state(items, key="status"):
    return {item["id"]: item for item in items}


def checks(project):
    """Return actionable issues without asserting missing work is complete."""
    brief = normalize_production_brief(project)
    issues = []
    stage_order = [key for key, _, _ in WORKFLOW_STAGES]
    stage = stage_order.index(brief["workflow"]["status"])
    author = brief["author"]
    for key, label in (("characterName", "角色名称"), ("title", "称号"), ("role", "职责 / 战斗定位"), ("race", "种族"), ("baseForm", "进化前形态"), ("evolvedForm", "进化后形态")):
        if not author.get(key):
            issues.append({"level": "todo", "page": "production", "text": f"作者填写包缺少{label}"})
    for plan_key, label in (("activeSkill", "主动技能"), ("pf", "PF"), ("leader", "队长技")):
        if not brief["plans"][plan_key]["name"]:
            issues.append({"level": "todo", "page": "production", "text": f"{label}尚未填写名称"})
        if not brief["plans"][plan_key]["authorDescription"]:
            issues.append({"level": "todo", "page": "production", "text": f"{label}尚未填写自然语言描述"})
        if stage >= 1 and brief["plans"][plan_key]["nativeSupport"] in ("unknown", "needs_verification"):
            issues.append({"level": "warning", "page": "production", "text": f"{label}的原生机制支持范围待制作方核验"})
    for plan in brief["plans"]["abilities"]:
        if plan["authorDescription"] or plan["name"]:
            if not plan["name"]:
                issues.append({"level": "todo", "page": "production", "text": f"能力 {plan['slot']} 只有说明，缺少名称"})
            if not plan["authorDescription"]:
                issues.append({"level": "todo", "page": "production", "text": f"能力 {plan['slot']} 只有名称，缺少自然语言说明"})
            if stage >= 1 and plan["nativeSupport"] in ("unknown", "needs_verification"):
                issues.append({"level": "warning", "page": "production", "text": f"能力 {plan['slot']} 的原生机制支持范围待制作方核验"})
    assets = project.get("assets", {}) if isinstance(project.get("assets", {}), dict) else {}
    for item in brief["resources"]:
        if item["required"] and item["status"] == "missing":
            issues.append({"level": "todo", "page": "production", "text": f"资源待补：{item['label']}", "id": item["id"]})
        if item["status"] == "needs_review":
            issues.append({"level": "warning", "page": "production", "text": f"资源待核验：{item['label']}", "id": item["id"]})
        if item["status"] in ("provided", "reuse_official") and not item["assetIds"]:
            issues.append({"level": "warning", "page": "production", "text": f"{item['label']}标记为已有，但尚未关联工程素材", "id": item["id"]})
        missing_assets = [aid for aid in item["assetIds"] if aid not in assets]
        if missing_assets:
            issues.append({"level": "warning", "page": "production", "text": f"{item['label']}引用了不存在的工程素材：{'、'.join(missing_assets)}", "id": item["id"]})
    voices = brief["voices"]
    for kind, items in (("语音", voices), ("音效", brief["sounds"])):
      for item in items:
          if item["required"] and item["status"] == "missing":
              issues.append({"level": "todo", "page": "production", "text": f"{kind}待补：{item['label']}", "id": item["id"]})
          if item["status"] == "needs_review":
              issues.append({"level": "warning", "page": "production", "text": f"{kind}待核验：{item['label']}", "id": item["id"]})
          if item["status"] in ("provided", "reuse_official") and not item.get("assetId"):
              issues.append({"level": "warning", "page": "production", "text": f"{item['label']}已标记完成，但还没有关联工程音频", "id": item["id"]})
          if item["required"] and item["status"] == "not_applicable" and not item.get("notes"):
              issues.append({"level": "warning", "page": "production", "text": f"{item['label']}已标为不适用，请说明原因", "id": item["id"]})
          if item["assetId"] and item["assetId"] not in assets:
              issues.append({"level": "warning", "page": "production", "text": f"{item['label']}引用了不存在的工程音频素材：{item['assetId']}", "id": item["id"]})
    pairs = {}
    for item in voices:
        if item.get("pairId"):
            pairs.setdefault(item["pairId"], []).append(item)
    for pair, items in pairs.items():
        if len(items) > 1:
            missing = [item["label"] for item in items if item["status"] == "missing"]
            if missing:
                issues.append({"level": "warning", "page": "production", "text": f"进化前后语音未成对：{'、'.join(missing)}"})
    for item in brief["review"]:
        if item["state"] == "risk":
            issues.append({"level": "warning", "page": "production", "text": f"稳定经验存在风险：{item['label']}"})
        elif stage >= 1 and item["state"] == "unreviewed":
            issues.append({"level": "warning", "page": "production", "text": f"稳定经验待确认：{item['label']}"})
    if not brief["acceptance"]["previewIsNotCombat"]:
        issues.append({"level": "warning", "page": "production", "text": "必须明确技能预览不等于实战验收"})
    if stage >= 4 and brief["acceptance"]["practiceBattleStatus"] == "not_run":
        issues.append({"level": "info", "page": "production", "text": "尚未进行本地练习战；需覆盖自动战斗和目标阵容"})
    if stage >= 4 and not brief["acceptance"]["localCdnVersion"]:
        issues.append({"level": "info", "page": "production", "text": "尚未记录本地 CDN 版本；正式云服版本应单独记录"})
    handoff = brief["workflow"]["handoff"]
    for row in handoff:
        if row["id"] == brief["workflow"]["status"] and not row["complete"]:
            issues.append({"level": "todo", "page": "production", "text": f"当前阶段未完成：{row['label']}"})
    return issues


def export_handoff(project):
    """Export a small JSON handoff that contains no binary assets or credentials."""
    brief = normalize_production_brief(project)
    return {
        "schema": "starpoint-character-production-handoff-v1",
        "version": 1,
        "project": {"id": project.get("id", ""), "name": project.get("name", ""), "revision": project.get("revision", 0)},
        "identity": copy.deepcopy(project.get("identity", {})),
        "productionBrief": brief,
        "legacyGameplay": copy.deepcopy(project.get("gameplay", {})),
        "nativeGameplayPresent": bool(project.get("nativeGameplay")),
        "resourceSummary": {
            "assets": len(project.get("assets", {})),
            "resourceStates": {item["id"]: item["status"] for item in brief["resources"]},
            "voiceStates": {item["id"]: item["status"] for item in brief["voices"]},
            "soundStates": {item["id"]: item["status"] for item in brief["sounds"]},
        },
        "checks": checks(project),
        "gameReady": False,
        "note": "这是作者填写包和制作方交接资料，不是可直接安装的游戏补丁。",
    }
