"""Portable, non-executable handoff to the MOD character production workflow.

This module reads only references belonging to an authoring project.  It never
loads the MOD GUI, resolves a live store, allocates game IDs, or writes assets.
Design prose and preserved official rows are deliberately separate.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path


SCHEMA = "starpoint-character-mod-handoff-v1"
GAMEPLAY_SCHEMA = "starpoint-gameplay-design-v1"
REFERENCE_LIMIT = 16 * 1024 * 1024
SOURCE_FILES = {
    "character": "data_readable/character.json",
    "characterText": "data_readable/character_text.json",
    "abilities": "data_readable/abilities.json",
    "leaderAbility": "data_readable/leader_ability.json",
    "actionSkill": "data_readable/action_skill.json",
    "switchedSkill": "data_readable/switched_skill.json",
    "status": "data_readable/status.json",
    "upskill": "data_readable/upskill.json",
    "speech": "data_readable/character_speech.json",
    "skillPreview": "data_readable/skill_preview.json",
    "assetReferences": "data_readable/master_asset_references.json",
}


def default_gameplay():
    """A fresh artist-facing design, not a fabricated set of ability rows."""
    return {
        "schema": GAMEPLAY_SCHEMA,
        "skill": {"name": "", "description": "", "energy": None, "behavior": ""},
        "leader": {"name": "", "description": ""},
        "abilities": [
            {"slot": n, "name": "", "description": "", "mainOnly": False}
            for n in range(1, 7)
        ],
        "uniqueConditions": [],
        "growth": {"templateId": "", "notes": ""},
        "notes": "",
    }


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def normalize_gameplay(p):
    """Validate and copy a project's design; the caller decides whether to save it."""
    value = copy.deepcopy(p.get("gameplay", {}))
    if not isinstance(value, dict):
        raise ValueError("玩法设计必须是对象")
    if value.get("schema", GAMEPLAY_SCHEMA) != GAMEPLAY_SCHEMA:
        raise ValueError("玩法设计版本不受支持")
    result = default_gameplay()
    result.update(value)
    for key in ("skill", "leader", "growth"):
        supplied = value.get(key, {})
        if not isinstance(supplied, dict):
            raise ValueError("玩法设计的 " + key + " 必须是对象")
        result[key] = {**default_gameplay()[key], **supplied}
    # Older projects kept the skill's display text outside gameplay.
    legacy = p.get("skill", {})
    if not isinstance(legacy, dict):
        raise ValueError("技能资料必须是对象")
    for key in ("name", "description"):
        if not isinstance(result["skill"][key], str):
            raise ValueError("技能名称与说明必须是文本")
        if result["skill"][key] == "":
            result["skill"][key] = legacy.get(key, "")
    supplied_slots = value.get("abilities", [])
    if not isinstance(supplied_slots, list):
        raise ValueError("能力设计必须是六个槽位的数组")
    slots = {item["slot"]: item for item in default_gameplay()["abilities"]}
    seen = set()
    for item in supplied_slots:
        slot = item.get("slot") if isinstance(item, dict) else None
        if isinstance(slot, bool) or not isinstance(slot, int) or slot not in slots or slot in seen:
            raise ValueError("能力槽位必须是互不重复的 1 至 6")
        seen.add(slot)
        slots[slot].update(item)
    result["abilities"] = list(slots.values())

    def text(value, label, limit=12000):
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError(label + f"必须是 {limit} 字以内的文本")

    for label, record in [("技能", result["skill"]), ("队长技", result["leader"])]:
        text(record["name"], label + "名称", 200)
        text(record["description"], label + "说明")
    text(result["skill"]["behavior"], "技能行为说明")
    energy = result["skill"]["energy"]
    if energy is not None and (isinstance(energy, bool) or not isinstance(energy, int) or not 1 <= energy <= 9999):
        raise ValueError("技能能量必须为 1 至 9999 的整数；未确定时留空")
    for item in result["abilities"]:
        text(item["name"], "能力名称", 200)
        text(item["description"], "能力说明")
        if not isinstance(item["mainOnly"], bool):
            raise ValueError("能力的主位限定必须是开关值")
    text(result["growth"]["templateId"], "成长参考角色编号", 100)
    text(result["growth"]["notes"], "成长说明")
    text(result["notes"], "玩法备注", 20000)
    if not isinstance(result["uniqueConditions"], list) or len(result["uniqueConditions"]) > 128:
        raise ValueError("固有状态设计必须是至多 128 项的数组")
    for item in result["uniqueConditions"]:
        if not isinstance(item, dict):
            raise ValueError("固有状态设计项必须是对象")
        text(item.get("name", ""), "固有状态名称", 200)
        text(item.get("description", ""), "固有状态说明")
    # Validate JSON serializability and reject non-finite values without losing
    # extension fields supplied by later versions of the same design schema.
    _canonical(result)
    return result


_design = normalize_gameplay


def _read(store, p, name):
    if name not in p.get("referenceFiles", []):
        return None
    project = store.directory(p["id"]).resolve()
    root = (project / "reference").resolve()
    target = (root / Path(name)).resolve()
    if not root.is_relative_to(project) or not target.is_relative_to(root):
        raise ValueError("角色定义参考文件超出工程目录")
    if not target.is_file() or target.stat().st_size > REFERENCE_LIMIT:
        raise ValueError("角色定义参考文件缺失或过大：" + name)
    raw = target.read_bytes()
    if len(raw) > REFERENCE_LIMIT:
        raise ValueError("角色定义参考文件过大：" + name)
    data = json.loads(raw.decode("utf-8-sig"))
    _canonical(data)
    return {"path": name, "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw), "data": data}


def _selection(record, key):
    if not record or key is None:
        return None
    data = record["data"]
    if not isinstance(data, dict):
        return None
    selected = data.get("selected", {})
    return selected.get(str(key)) if isinstance(selected, dict) else None


def _first_row(selection):
    if not isinstance(selection, dict):
        return None
    rows = selection.get("rows", [])
    return rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], list) else None


def _source_definition(p, records):
    template = p.get("template") or {}
    native = (p.get('nativeGameplay') or {}).get('source', {}).get('data', {})
    cid = native.get('character', {}).get('id') or template.get("id")
    character = _selection(records.get("character"), cid)
    row = _first_row(character)
    missing, slots = [], []
    if row is None or len(row) < 25:
        missing.append("character 原始行与真实引用键")
        row = []
    if not _selection(records.get("characterText"), cid):
        missing.append("character_text 原始文本行")
    leader_key = row[17] if len(row) > 17 else None
    leader = _selection(records.get("leaderAbility"), leader_key)
    if leader_key not in ("", "(None)", None) and not leader:
        missing.append("leader_ability 的实际引用行：" + str(leader_key))
    elif not row:
        missing.append("leader_ability 的实际引用键与原始行")
    for slot in range(1, 7):
        key = row[18 + slot] if len(row) > 18 + slot else None
        selected = _selection(records.get("abilities"), key)
        known_absent = bool(row) and key in ("", "(None)")
        status = "source_preserved" if selected else "not_used_by_source" if known_absent else "missing_source"
        slots.append({"slot": slot, "sourceKey": key, "status": status,
                      "sourceRows": copy.deepcopy(selected)})
        if status == "missing_source":
            missing.append("ability 槽位 " + str(slot) + " 的实际引用行")
    action = records.get("actionSkill", {}).get("data", {})
    action_key = row[8] if len(row) > 8 and row[8] not in ("", "(None)") else (row[0] if row else None)
    if not isinstance(action, dict) or not action.get("rows") or (action_key is not None and action.get("outer_key") != action_key):
        missing.append("action_skill 原始版本、能量和程序绑定行")
    is_template = p.get("kind") == "template" or bool(template) or bool(native)
    return {
        "status": "needs_definition_pack" if is_template and missing else "source_data_preserved" if is_template else "original_design",
        "needsDefinitionPack": bool(is_template and missing),
        "missing": missing if is_template else [],
        "characterId": cid,
        "characterRows": copy.deepcopy(character),
        "leader": {"sourceKey": leader_key, "sourceRows": copy.deepcopy(leader)},
        "abilities": slots,
        "records": records,
        "note": "能力设计不等于官方能力；来源表缺失时需另导入角色定义包。保留的原始行尚未转换成新角色行。",
    }


def _programs(store, p):
    dep = _read(store, p, "data_readable/skill_dependencies.json")
    result = []
    if dep:
        if not isinstance(dep["data"], dict) or not isinstance(dep["data"].get("programs", []), list):
            raise ValueError("参考技能程序清单无效")
        values = dep["data"].get("programs", [])
        for program in values:
            if not isinstance(program, dict) or not isinstance(program.get("logical"), str) or "tree" not in program:
                raise ValueError("参考技能程序记录无效")
            tree = copy.deepcopy(program["tree"])
            result.append({"logical": program["logical"], "tree": tree,
                           "sha256": hashlib.sha256(_canonical(tree)).hexdigest(),
                           "sha256Encoding": "canonical-json-utf8",
                           "referencePath": dep["path"], "referenceSha256": dep["sha256"]})
    # The older single-character reference exporter uses individual decoded files.
    known = {item["logical"] for item in result}
    for name in sorted(p.get("referenceFiles", [])):
        if not name.startswith("data_readable/action_dsl/decoded/") or not name.endswith(".json"):
            continue
        if "\\" in name or ":" in name or ".." in name.split("/"):
            raise ValueError("参考技能程序路径无效")
        ref = _read(store, p, name)
        data = ref["data"]
        if not isinstance(data, dict) or not isinstance(data.get("logical_path"), str) or "tree" not in data:
            raise ValueError("参考技能程序记录无效")
        if data["logical_path"] in known:
            continue
        known.add(data["logical_path"])
        result.append({"logical": data["logical_path"], "tree": copy.deepcopy(data["tree"]),
                       "sha256": hashlib.sha256(_canonical(data["tree"])).hexdigest(),
                       "sha256Encoding": "canonical-json-utf8", "referencePath": name,
                       "referenceSha256": ref["sha256"]})
    return result


def export_contract(store, p):
    """Return a versioned, read-only design handoff, never an installable pack."""
    records = {}
    for label, name in SOURCE_FILES.items():
        record = _read(store, p, name)
        if record:
            records[label] = record
    native = p.get('nativeGameplay')
    if native:
        from native_gameplay import validate_native
        validate_native(native)
        source_records = native['source']['data']['character']['records']
        for label, name in SOURCE_FILES.items():
            key = name.removeprefix('data_readable/').removesuffix('.json')
            if key in source_records:
                data = copy.deepcopy(source_records[key])
                records[label] = {'path': 'nativeGameplay.source.' + key, 'sha256': hashlib.sha256(_canonical(data)).hexdigest(), 'data': data}
    code = p.get("identity", {}).get("code", "")
    valid_code = bool(re.fullmatch(r"[a-z][a-z0-9_]{1,70}", code))
    animations = []
    for a in p.get("animations", []):
        variant = a.get("variant", "normal")
        stem = "pixelart" if variant == "normal" else "special"
        animations.append({"id": a["id"], "slot": a.get("slot"), "variant": variant,
                           "hasFrames": bool(a.get("clips")),
                           "logical": f"character/{code}/pixelart/{stem}" if valid_code else None})
    effects = []
    for effect in p.get("effects", []):
        effects.append({"id": effect["id"], "name": effect.get("name", ""),
                        "source": copy.deepcopy(effect.get("native")),
                        "logical": f"battle/effect/skill_unique/{code}/{effect['id']}/effect" if valid_code else None,
                        "sequence": effect.get("native", {}).get("sequence", "neutral"),
                        "hasFrames": bool(effect.get("clips") or effect.get("nativeFrames")),
                        "soundEvents": copy.deepcopy(effect.get("soundEvents", []))})
    audio = []
    for item in p.get("voices", []) + p.get("sounds", []):
        asset = p.get("assets", {}).get(item.get("asset"), {})
        audio.append({**copy.deepcopy(item),
                      "logical": f"sound_effect/character_studio/{code}/{item['asset']}" if valid_code else None,
                      "sourceLogical": item.get("logical"),
                      "compilerCandidate": asset.get("mime") == "audio/mpeg",
                      "encodingStatus": "requires_compiler_verification"})
    return {
        "schema": SCHEMA, "schemaVersion": 1,
        "project": {"id": p["id"], "name": p.get("name", ""), "revision": p.get("revision", 0)},
        "identity": copy.deepcopy(p.get("identity", {})), "template": copy.deepcopy(p.get("template")),
        "gameplayDesign": normalize_gameplay(p), "sourceDefinition": _source_definition(p, records),
        "nativeGameplay": copy.deepcopy(native),
        "sourcePrograms": _programs(store, p),
        "resourceMapping": {"animations": animations, "effects": effects, "audio": audio,
                            "portraits": copy.deepcopy(p.get("portraits", {})),
                            "crops": copy.deepcopy(p.get("crops", {})),
                            "assets": copy.deepcopy(p.get("assets", {}))},
        "skillPreview": copy.deepcopy(p.get("scene", {})),
        "integration": {
            "status": "editable_native_draft" if native else "design_handoff", "gameReady": False, "directModImport": False,
            "modStudioProjectImport": True, "nativeRowsEditable": bool(native),
            "writesLive": False, "allocatesGameIds": False,
            "nextAdapter": "隔离工作区转换 → wf_character_workspace → wf_character_pack preflight",
            "pending": ([] if native else ["导入角色定义包，读取真实主表引用并编辑能力行"]) + [
                "将设计的技能行为转换为 ActionDSL，并进行客户端运行校验",
                "分配新角色、词条、玛纳节点标识，并保持模板与新角色资源独立",
                "重写技能到特效与声音的绑定；组合预览时间线尚不是游戏 ActionDSL",
                "生成客户端及服务端角色表、成长、玛纳板和所有显示资源绑定",
                "校准 UI 图集与定位、Android/iOS 平台纹理、预载依赖",
                "执行原 MOD 隔离 preflight、存档兼容检查与客户端验收",
            ],
            "note": "工程可在 MOD 的角色工坊入口继续编辑；native-draft 是临时键草稿表，尚不是原 character-pack 发布格式。",
        },
    }
