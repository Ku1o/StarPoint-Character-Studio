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
AUTHOR_POLICY_STATES = (
    ("unmarked", "直接填写或提供文件"),
    ("needs_help", "请协助制作"), ("cannot_provide", "暂时无法提供"),
    ("explicit_reuse", "明确复用"), ("maker_derive", "由母版派生"),
    ("not_applicable", "不适用并说明理由"), ("maker_review", "请制作方确认"),
    ("author_pending", "稍后补充"),
)


def _author_policy():
    return {"state": "unmarked", "reason": "", "reference": ""}


def _normalize_author_policy(value):
    result = _merge_record(_author_policy(), value)
    result["state"] = _choice(result["state"], {key for key, _ in AUTHOR_POLICY_STATES}, "作者责任声明")
    for key in ("reason", "reference"):
        result[key] = _text(result[key], 4000)
    return result


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
        "authorPolicy": _author_policy(),
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
        "authorPolicy": _author_policy(),
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
        "entry": "",
        "authorPolicy": _author_policy(),
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
        "authorPolicy": {"voiceMode": "unmarked", "voiceReason": "", "voiceReference": "", "identity": {}},
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
    policy = _merge_record(base["authorPolicy"], supplied.get("authorPolicy", {}))
    policy["voiceMode"] = _choice(policy["voiceMode"], ("unmarked", "custom", "none", "reuse"), "配音意图")
    for key in ("voiceReason", "voiceReference"):
        policy[key] = _text(policy[key], 4000)
    identity_policies = policy.get("identity", {})
    if not isinstance(identity_policies, dict):
        raise ValueError("角色信息协助说明必须是对象")
    policy["identity"] = {key: _normalize_author_policy(value) for key, value in identity_policies.items()}
    result["authorPolicy"] = policy

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
    for key, value in supplied_plans.items():
        if key not in plans:
            plans[key] = copy.deepcopy(value)
    for key in ("activeSkill", "pf", "leader"):
        plans[key] = _merge_record(plans[key], supplied_plans.get(key, {}))
        plans[key]["nativeSupport"] = _choice(plans[key].get("nativeSupport"), NATIVE_SUPPORT, "原生机制支持")
        plans[key]["authorPolicy"] = _normalize_author_policy(plans[key].get("authorPolicy", {}))
        for field in base["plans"][key]:
            if field not in ("nativeSupport", "authorPolicy"):
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
        item["authorPolicy"] = _normalize_author_policy(item.get("authorPolicy", {}))
        for field in base["plans"]["abilities"][slot - 1]:
            if field not in ("slot", "nativeSupport", "authorPolicy"):
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
        item["authorPolicy"] = _normalize_author_policy(item.get("authorPolicy", {}))
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
        item["authorPolicy"] = _normalize_author_policy(item.get("authorPolicy", {}))
        item["status"] = _choice(item.get("status"), ITEM_STATUS, "语音状态")
        item["source"] = _choice(item.get("source"), VOICE_SOURCE, "语音来源")
        for key, limit in (("textJapanese", 4000), ("entry", 1000), ("dialect", 500), ("toneReference", 1000), ("volume", 100), ("duration", 100), ("filename", 260), ("encoding", 300), ("assetId", 100), ("notes", 8000)):
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


AUTHOR_FIELDS = (("characterName", "角色名称"), ("title", "称号"), ("role", "职责 / 战斗定位"),
                 ("race", "种族"), ("baseForm", "进化前形态"), ("evolvedForm", "进化后形态"))


def text_guidance(brief):
    """A text or a detailed assistance request can complete author intent only."""
    rows = []
    items = [("author", key, label, [brief["author"][key]], brief["authorPolicy"]["identity"].get(key, _author_policy()), True)
             for key, label in AUTHOR_FIELDS]
    items.extend(("plans", key, label, [brief["plans"][key]["name"], brief["plans"][key]["authorDescription"]],
                  brief["plans"][key]["authorPolicy"], True)
                 for key, label in (("activeSkill", "主动技能"), ("pf", "PF"), ("leader", "队长技")))
    items.extend(("plans.abilities", str(index), plan["label"], [plan["name"], plan["authorDescription"]],
                  plan["authorPolicy"], bool(plan["name"] or plan["authorDescription"] or plan["authorPolicy"]["state"] != "unmarked"))
                 for index, plan in enumerate(brief["plans"]["abilities"]))
    for kind, key, label, values, policy, required in items:
        state = policy["state"]
        supplied = all(value.strip() for value in values)
        declared = state not in ("unmarked", "author_pending") and bool(policy["reason"].strip())
        if state in ("explicit_reuse", "maker_derive"):
            declared = declared and bool(policy["reference"].strip())
        complete = supplied or declared
        pending = state != "unmarked"
        path = "productionBrief." + kind + "." + key
        problems = []
        if pending:
            problems.append({"level": "warning" if declared else "todo", "page": "production", "path": path + ".authorPolicy",
                             "owner": "maker" if declared else "author", "code": "text_assistance" if declared else "text_reason_missing",
                             "text": f"{label}：{dict(AUTHOR_POLICY_STATES)[state]}，制作方待确认" if declared else f"{label}请补充具体理由与希望协助的内容",
                             "nextStep": "说明希望的结果、无法提供的原因与已有参考；声明不会自动生成玩法或资源。"})
        rows.append({"kind": kind, "id": key, "label": label, "path": path, "required": required, "state": state,
                     "reason": policy["reason"], "reference": policy["reference"], "authorComplete": complete,
                     "makerPending": pending, "integrationVerified": False, "issues": problems})
    return rows


def author_guidance(project):
    """Describe author obligations and maker review from the brief's row schema.

    ``authorComplete`` means the author has supplied a usable intent/declaration.
    It never means a resource has passed native integration.
    """
    brief = normalize_production_brief(project)
    assets = project.get("assets", {}) if isinstance(project.get("assets"), dict) else {}
    rows = []
    global_voice = brief["authorPolicy"]
    for kind in ("resources", "voices", "sounds"):
        noun = {"resources": "资源", "voices": "语音", "sounds": "音效"}[kind]
        for index, item in enumerate(brief[kind]):
            policy = item["authorPolicy"]
            state, reason, reference = (policy[key].strip() for key in ("state", "reason", "reference"))
            status = item["status"]
            path = f"productionBrief.{kind}.{index}"
            problems = []
            author_complete = False
            maker_pending = False

            def issue(code, text, owner="maker", field="status", level="warning", next_step=""):
                problems.append({"code": code, "level": level, "page": "production", "id": item["id"],
                                 "path": path + "." + field, "owner": owner, "text": text,
                                 "nextStep": next_step or "补充此项说明，或与制作方确认可复用、可派生及不适用范围。"})

            ids = item.get("assetIds", []) if kind == "resources" else ([item["assetId"]] if item["assetId"] else [])
            missing_ids = [aid for aid in ids if aid not in assets]
            wrong_type = [aid for aid in ids if aid in assets and isinstance(assets[aid], dict)
                          and assets[aid].get("mime") and not assets[aid]["mime"].startswith("image/" if kind == "resources" else "audio/")]
            supplied = status in ("provided", "reuse_official")
            if supplied:
                maker_pending = True
                author_complete = bool(ids) and not missing_ids and not wrong_type
                if not ids:
                    issue("asset_unlinked", f"{item['label']}标记为已有，但尚未关联工程{'素材' if kind == 'resources' else '音频'}", field="assetIds" if kind == "resources" else "assetId", next_step="关联实际导入的素材；文件名和已有状态不能代替文件。")
            if missing_ids:
                author_complete = False
                issue("asset_missing", f"{item['label']}引用了不存在的工程{'素材' if kind == 'resources' else '音频素材'}：{'、'.join(missing_ids)}", field="assetIds" if kind == "resources" else "assetId", next_step="重新导入原稿并关联有效素材；保留原稿文件。")
            if wrong_type:
                author_complete = False
                issue("asset_type", f"{item['label']}关联的素材类型不符：{'、'.join(wrong_type)}", field="assetIds" if kind == "resources" else "assetId")
            voice_content_required = kind == "voices" and (status == "provided" or (status == "reuse_official" and bool(ids)))
            if voice_content_required:
                for field, label in (("entry", "播放入口"), ("textJapanese", "完整台词")):
                    if not item[field].strip():
                        author_complete = False
                        issue("voice_" + field + "_missing", f"{item['label']}缺少{label}", "author", field, "todo", "补充实际入口和完整原文；无台词需明确写出原因，不用删去句尾。")

            # A declaration resolves intent only. It cannot hide a broken file
            # which is still marked provided, nor an incomplete provided voice.
            broken_provided = (status == "provided" and not author_complete) or bool(missing_ids or wrong_type) or (voice_content_required and not author_complete)
            if state == "unmarked":
                if status == "not_applicable":
                    author_complete = bool(item["notes"].strip()) and not broken_provided
                    if not author_complete:
                        issue("reason_missing", f"{item['label']}已标为不适用，请说明原因", "author", "notes", "todo")
                    maker_pending = True
                elif status == "reuse_official":
                    maker_pending = True
                    issue("reuse_unmarked", f"{item['label']}复用范围未标注，待制作方确认", field="authorPolicy.reference")
                elif status in ("missing", "needs_review"):
                    author_complete = False
                    if item["required"] and status == "missing":
                        issue("author_unmarked", f"{noun}待补：{item['label']}", "author", "authorPolicy.state", "todo")
                    elif status == "needs_review":
                        maker_pending = True
                        issue("maker_review", f"{noun}待核验：{item['label']}")
                if kind == "voices" and status == "missing" and global_voice["voiceMode"] in ("none", "reuse"):
                    valid = bool(global_voice["voiceReason"].strip()) and (global_voice["voiceMode"] == "none" or bool(global_voice["voiceReference"].strip()))
                    problems = [p for p in problems if p["code"] != "author_unmarked"]
                    author_complete = valid
                    maker_pending = True
                    if not valid:
                        issue("voice_policy_incomplete", f"{item['label']}的整体配音声明缺少理由或复用来源", "author", "authorPolicy.state", "todo")
                    else:
                        state = "not_applicable" if global_voice["voiceMode"] == "none" else "explicit_reuse"
                        reason, reference = global_voice["voiceReason"], global_voice["voiceReference"]
            elif state == "author_pending":
                author_complete = False
                issue("author_pending", f"{noun}待补：{item['label']}", "author", "authorPolicy.state", "todo")
            else:
                maker_pending = True
                declaration_valid = bool(reference) if state in ("explicit_reuse", "maker_derive") else bool(reason)
                author_complete = declaration_valid and not broken_provided
                if not declaration_valid:
                    issue("declaration_incomplete", f"{item['label']}的{dict(AUTHOR_POLICY_STATES)[state]}声明缺少{'来源 / 母版' if state in ('explicit_reuse', 'maker_derive') else '理由'}", "author", "authorPolicy.reference" if state in ("explicit_reuse", "maker_derive") else "authorPolicy.reason", "todo")
            if maker_pending and not any(p["owner"] == "maker" for p in problems):
                issue("integration_pending", f"{item['label']}作者意图已记录，制作方接入待核", next_step="核对映射、派生结果与游戏实际入口；作者声明不等于原生验收。")
            rows.append({"kind": kind, "id": item["id"], "label": item["label"], "path": path,
                         "required": item["required"], "state": state, "reason": reason, "reference": reference,
                         "status": status, "authorComplete": author_complete,
                         "makerPending": maker_pending, "integrationVerified": False, "issues": problems})
    text_rows = text_guidance(brief)
    return {"schema": "starpoint-character-author-guidance-v1", "rows": rows, "textRows": text_rows,
            "textAuthorPending": [row["path"] for row in text_rows if row["required"] and not row["authorComplete"]],
            "policyStates": [{"value": key, "label": label} for key, label in AUTHOR_POLICY_STATES],
            "authorPending": [row["path"] for row in rows if row["required"] and not row["authorComplete"]],
            "makerPending": [row["path"] for row in rows if row["makerPending"]], "gameReady": False}


def checks(project):
    """Return actionable issues without asserting missing work is complete."""
    brief = normalize_production_brief(project)
    issues = []
    stage_order = [key for key, _, _ in WORKFLOW_STAGES]
    stage = stage_order.index(brief["workflow"]["status"])
    author = brief["author"]
    text_rows = {row["path"]: row for row in text_guidance(brief)}
    for key, label in AUTHOR_FIELDS:
        if not author.get(key, "").strip() and not text_rows["productionBrief.author." + key]["authorComplete"]:
            issues.append({"level": "todo", "page": "production", "text": f"作者填写包缺少{label}"})
    for plan_key, label in (("activeSkill", "主动技能"), ("pf", "PF"), ("leader", "队长技")):
        complete = text_rows["productionBrief.plans." + plan_key]["authorComplete"]
        if not brief["plans"][plan_key]["name"].strip() and not complete:
            issues.append({"level": "todo", "page": "production", "text": f"{label}尚未填写名称"})
        if not brief["plans"][plan_key]["authorDescription"].strip() and not complete:
            issues.append({"level": "todo", "page": "production", "text": f"{label}尚未填写自然语言描述"})
        if stage >= 1 and brief["plans"][plan_key]["nativeSupport"] in ("unknown", "needs_verification"):
            issues.append({"level": "warning", "page": "production", "text": f"{label}的原生机制支持范围待制作方核验"})
    for index, plan in enumerate(brief["plans"]["abilities"]):
        if plan["authorDescription"] or plan["name"]:
            complete = text_rows[f"productionBrief.plans.abilities.{index}"]["authorComplete"]
            if not plan["name"] and not complete:
                issues.append({"level": "todo", "page": "production", "text": f"能力 {plan['slot']} 只有说明，缺少名称"})
            if not plan["authorDescription"] and not complete:
                issues.append({"level": "todo", "page": "production", "text": f"能力 {plan['slot']} 只有名称，缺少自然语言说明"})
            if stage >= 1 and plan["nativeSupport"] in ("unknown", "needs_verification"):
                issues.append({"level": "warning", "page": "production", "text": f"能力 {plan['slot']} 的原生机制支持范围待制作方核验"})
    guidance = author_guidance(project)
    for row in guidance["textRows"]:
        issues.extend(row["issues"])
    for row in guidance["rows"]:
        issues.extend(row["issues"])
    voices = brief["voices"]
    voice_rows = {row["id"]: row for row in guidance["rows"] if row["kind"] == "voices"}
    pairs = {}
    for item in voices:
        if item.get("pairId"):
            pairs.setdefault(item["pairId"], []).append(item)
    for pair, items in pairs.items():
        if len(items) > 1:
            missing = [item["label"] for item in items if item["status"] == "missing" and not voice_rows[item["id"]]["authorComplete"]]
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


def _md(value):
    return str(value).replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def author_submission_form(project=None):
    """Generate the submission worksheet from the same schema as checks/UI."""
    project = project or {"productionBrief": default_production_brief(), "assets": {}}
    brief = normalize_production_brief(project)
    lines = ["# 素材提交填写表", "", "空白或未标注表示尚未说明，不等于完成或不适用。",
             "作者填写角色意图；游戏编号、DSL、封装、图集和版本链由制作方核验。", "", "## 基本信息", "",
             "| 项目 | 填写 |", "| --- | --- |"]
    for key, label in (("characterName", "角色名"), ("title", "角色资料头衔（与玩家铭牌分开）"), ("element", "属性"), ("role", "职责 / 战斗定位"), ("race", "种族"), ("baseForm", "基础形态"), ("evolvedForm", "进化形态 / 复用")):
        lines.append(f"| {label} | {_md(brief['author'][key])} |")
    lines.extend(["", "## 玩法", "", "| 项目 | 名称 | 自然语言意图 | 对象 / 触发 / 数值 / 时长 | 待确认 |", "| --- | --- | --- | --- | --- |"])
    for plan in [brief["plans"][key] for key in ("activeSkill", "pf", "leader")] + brief["plans"]["abilities"]:
        details = " / ".join(plan[key] for key in ("target", "trigger", "multiplier", "duration") if plan[key])
        lines.append(f"| {_md(plan['label'])} | {_md(plan['name'])} | {_md(plan['authorDescription'])} | {_md(details)} | {_md(plan['verificationItems'])} |")
    lines.extend(["", "## 素材、语音与音效", "", "状态选择：" + " / ".join(label for _, label in AUTHOR_POLICY_STATES) + "。",
                  "明确复用请写来源；制作方可派生请选择母版或写参考名称；无法提供可说明具体困难与希望协助的内容。",
                  "整体配音意图：" + _md(brief["authorPolicy"]["voiceMode"]) + "；理由：" + _md(brief["authorPolicy"]["voiceReason"]) + "；复用来源：" + _md(brief["authorPolicy"]["voiceReference"]), "",
                  "| 用途 / schema ID | 制作所需 | 作者责任声明 | 原稿 / 母版 / 复用来源 | 理由 / 待确认 |", "| --- | --- | --- | --- | --- |"])
    for kind in ("resources", "voices", "sounds"):
        for item in brief[kind]:
            policy = item["authorPolicy"]
            lines.append(f"| {_md(item['label'])} / `{kind}.{item['id']}` | {'需要明确说明' if item['required'] else '按需选填'} | {dict(AUTHOR_POLICY_STATES)[policy['state']]} | {_md(policy['reference'])} | {_md(policy['reason'])} |")
    lines.extend(["", "## 角色与玩法协助说明", "", "| 项目 | 声明 | 详细理由 / 希望的结果 | 参考 | 当前状态 |", "| --- | --- | --- | --- | --- |"])
    for row in text_guidance(brief):
        if row["state"] != "unmarked":
            lines.append(f"| {_md(row['label'])} | {dict(AUTHOR_POLICY_STATES)[row['state']]} | {_md(row['reason'])} | {_md(row['reference'])} | {'意图已说明，制作方待核' if row['authorComplete'] else '说明待补充'} |")
    lines.extend(["", "## 动作与演出意图", "", "原精灵图 / 每格尺寸 / 格号起点：____；身体足底或悬浮点：____。", "",
                  "| 动作 | 源格号 / 文件 | 时长 / 循环 | 返回动作 | 纯本体 / 合成 / 可派生范围 |", "| --- | --- | --- | --- | --- |",
                  "| 停留 / 前后移动 | | | | |", "| 施法起手 / 结束恢复 | | | | |", "| 倒下 / 灵魂 / 复活 / 特殊形态 | | | | |", "",
                  "技能效果请说明起手、命中、结束的顺序，跟随角色、固定场地或敌人绑定；表现区域与伤害区域分开。", "",
                  "## 台词与原声", "", "| 用途 / 形态 / 条件 | 实际播放入口 | 完整原文 | 原声文件 | 可修改范围 |", "| --- | --- | --- | --- | --- |"])
    for item in brief["voices"]:
        lines.append(f"| {_md(item['label'])} | {_md(item['entry'])} | {_md(item['textJapanese'])} | {_md(item['filename'])} | {_md(item['notes'])} |")
    lines.extend(["", "获取全文保留词义与手动换行；排版候选需展示差异，近似预览不能代替首次获取画面。", "",
                  "## 玩家铭牌（独立选填）", "", "角色资料头衔不会变成可佩戴铭牌。无需求可声明不适用；多款按需增行。", "",
                  "| 名称 | 字形 / 配色 / 标志 | 草图 / 母版 | 可调整范围 |", "| --- | --- | --- | --- |", "| | | | |", "",
                  "## 提交前核对", "", "- [ ] 原稿与可编辑源文件保留，候选不覆盖原稿。", "- [ ] 每项用途、复用来源、派生母版或不适用理由已说明。",
                  "- [ ] 动作格号、身体定位、循环和恢复意图已说明。", "- [ ] 已提供完整台词与入口，或明确无配音；音效另填。", "- [ ] 工程导出与制作交接一并保留，待核范围列明。", ""])
    return "\n".join(lines)


def author_readme(project=None):
    """Generate author instructions and current obligations, without native claims."""
    project = project or {"productionBrief": default_production_brief(), "assets": {}}
    guidance = author_guidance(project)
    lines = ["# 稿主素材准备指南", "", "先说明角色意图并保留原稿。制作方处理游戏编号、DSL、PNG 封装、声音编码与版本链。", "",
             "## 从这里开始", "", "1. 填角色名、资料头衔、属性、形态、定位和玩法意图。", "2. 导入原稿并按用途关联；保留原文件名、原目录与可编辑源文件。",
             "3. 一张母版可派生多个 UI 小图；进化可明确复用，不必为每个用途重复绘制。", "4. 在每项声明中选择复用、可派生、不适用、请协助制作或暂时无法提供，并说明理由与参考。角色和玩法未定也可这样交接。",
             "5. 没有配音时填写整体无配音和理由；音效单独说明。已有声音仍须有实际入口和完整台词。", "6. 导出工程和制作交接，核对下面的作者补充与制作方待核。", "",
             "## 状态说明", "", "| 作者责任声明 | 下一步 |", "| --- | --- |"]
    meanings = {"unmarked": "尚未说明；旧工程缺省也保持未标注，不会自动通过。", "author_pending": "作者补充原稿或意图；可改为明确复用、可派生或不适用并说明。",
                "explicit_reuse": "写清官方角色 / 资源、已有形态或工程素材来源；制作方核对映射和接入。", "maker_derive": "选择母版或写参考名称与可调整范围；制作方给派生结果和预览。",
                "not_applicable": "写清无需求或不适用理由；制作方仍核对必要入口。", "maker_review": "写出具体待核问题；制作方确认实现范围。",
                "needs_help": "说明期望结果、希望制作方协助的部分及已有参考；只完成作者意图，不表示已收到素材。",
                "cannot_provide": "说明暂时无法提供的原因、可接受的替代方案及已有参考；制作方确认后续安排，资源保持缺失或待核。"}
    for key, label in AUTHOR_POLICY_STATES:
        lines.append(f"| {label} | {meanings[key]} |")
    lines.extend(["", "## 角色与玩法协助说明", ""])
    for row in guidance["textRows"]:
        if row["state"] != "unmarked":
            lines.append(f"- {row['label']}：{dict(AUTHOR_POLICY_STATES)[row['state']]}；理由：{row['reason']}；参考：{row['reference']}；制作方待核。")
            for issue in row["issues"]:
                lines.append(f"- `{issue['path']}`：{issue['text']}。{issue['nextStep']}")
    lines.extend(["", "作者说明完成与制作接入通过分别记录；复用、可派生、不适用和已提供都不会自动证明游戏可用。", "",
                  "## 原稿与动作", "", "原始像素尺寸、每格大小、格号从 0 还是 1 开始、动作用途都要说明。逐帧记录顺序、时长、循环、返回状态和身体足底。",
                  "纯本体与含召唤物 / 附属物的合成帧分开；未画动作明确标注。旧角色的格号或配方不能作为所有角色的默认。", "",
                  "## 演出与声音", "", "起手、命中与结束分别说明位置、跟随对象与时序。表现区域和实际伤害判定分开；编排预览不代表原生脚本或实战通过。",
                  "保留最高质量原声和完整句尾。制作方按同声道参考检查编码后响度、真峰、削波和时长；试听发声不代表全文或入口验收。",
                  "获取台词保留全文和手动换行，排版候选展示差异，不默默删词；近似气泡预览仍需实际首次获取验证。", "",
                  "## 两种称号", "", "角色资料头衔与可佩戴玩家铭牌分开。铭牌按需求选填，可先交草图；最终 320×50 透明 RGBA，还需 160×25 缩小预览和实际内框核对。", "",
                  "## 当前清单", "", "| 用途 / 位置 | 作者责任声明 | 作者说明 | 制作方 |", "| --- | --- | --- | --- |"])
    for row in guidance["rows"]:
        lines.append(f"| {_md(row['label'])} / `{row['path']}` | {dict(AUTHOR_POLICY_STATES)[row['state']]} | {'已说明' if row['authorComplete'] else '待补充 / 未标注'} | {'接入待核' if row['makerPending'] else '尚未接收'} |")
    lines.extend(["", "## 具体问题与下一步", ""])
    for row in guidance["rows"]:
        for issue in row["issues"]:
            lines.append(f"- `{issue['path']}`：{issue['text']}。{issue['nextStep']}")
    lines.extend(["", "工程、原稿接收身份、派生映射、动作声明、自检、编译报告与未覆盖项一并交接。gameReady 保持 false，直到对应接入证据满足。", ""])
    return "\n".join(lines)


def export_handoff(project):
    """Export a small JSON handoff that contains no binary assets or credentials."""
    brief = normalize_production_brief(project)
    return {
        "schema": "starpoint-character-production-handoff-v1",
        "version": 1,
        "project": {"id": project.get("id", ""), "name": project.get("name", ""), "revision": project.get("revision", 0)},
        "identity": copy.deepcopy(project.get("identity", {})),
        "productionBrief": brief,
        "authorGuidance": author_guidance(project),
        "authorGuide": author_readme(project),
        "authorSubmissionForm": author_submission_form(project),
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
