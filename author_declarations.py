"""Strict, additive author declarations and the shared handoff/check report.

Missing optional declarations are unknown, never an implicit approval or denial.
The report is read-only; draft persistence/export does not enforce compile gates.
"""
from __future__ import annotations

import copy
import html
from collections import Counter

from studio_core import (StudioError, BASE_STATE_SLOTS, COMPANION_STATE_SLOTS,
                         KEY_UI_SLOTS, UI_SLOTS, UI_MASK_VALUES, EFFECT_ORIGINS,
                         VOICE_ENTRIES, LABELS, animation_variant, clip_variant)


def _text(value):
    return value if isinstance(value, str) else ""


def _marked(value):
    return isinstance(value, str) and bool(value.strip())


def _flag(value):
    return type(value) is bool or value is None or (type(value) is str and value == "")


def _records(p, group):
    values = p.get(group, [])
    return [v for v in values if isinstance(v, dict)] if isinstance(values, list) else []


def make_issue(code, level, page, text, *, id="", position="", location="", fix="",
               blocking=False, declaration=False):
    """Stable fields plus the existing UI's combined ``text`` contract."""
    parts = [text]
    if position:
        parts.append("位置：" + position)
    if fix:
        parts.append("改法：" + fix)
    return {"code": code, "level": level, "page": page, "id": _text(id),
            "text": "　".join(parts), "summary": text, "position": position,
            "location": location, "fix": fix, "blocking": blocking,
            "declaration": declaration}


def normalize_declarations(p):
    """Fill only absent/null fields. Preserve malformed values for validation."""
    if not isinstance(p, dict):
        raise StudioError("作者声明必须附在工程对象中")

    def defaults(record, fields):
        for key, value in fields.items():
            if key not in record or record[key] is None:
                record[key] = copy.deepcopy(value)

    defaults(p, {"authorNotes": "", "uiDeclarations": {}, "voiceDeclarations": []})
    for group in ("animations", "effects"):
        for item in _records(p, group):
            defaults(item, {key: "" for key in ("purpose", "includesCompanion", "companionNote", "origin", "originNote")})
    if isinstance(p["uiDeclarations"], dict):
        for spec in p["uiDeclarations"].values():
            if isinstance(spec, dict):
                defaults(spec, {"autoCrop": "", "mask": "", "note": ""})
    for item in _records(p, "voiceDeclarations"):
        defaults(item, {key: "" for key in ("asset", "file", "entry", "usage", "text", "reused")})
    return p


def declaration_errors(p):
    """Return type/schema failures instead of leaking TypeError/AttributeError."""
    issues = []

    def invalid(page, rid, path, label, fix):
        issues.append(make_issue("declaration_type_invalid", "warning", page,
                                label + "取值或类型无效", id=rid, position=path,
                                location=path, fix=fix, blocking=True, declaration=True))

    def text_field(record, key, limit, page, rid, path):
        value = record.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > limit):
            invalid(page, rid, path + "." + key, key, f"填写不超过 {limit} 字的字符串；未标注使用空字符串")

    def flag_field(record, key, page, rid, path):
        if not _flag(record.get(key)):
            invalid(page, rid, path + "." + key, key, "只接受 JSON true、false 或空字符串；不要填写字符串或数字")

    def enum_field(record, key, allowed, page, rid, path):
        value = record.get(key)
        if value is not None and (not isinstance(value, str) or value not in ("", *allowed)):
            invalid(page, rid, path + "." + key, key, "选择 " + "/".join(allowed) + "；未标注使用空字符串")

    text_field(p, "authorNotes", 12000, "identity", "", "project")
    for group in ("animations", "effects", "voices", "sounds", "voiceDeclarations"):
        values = p.get(group)
        if values is None and group == "voiceDeclarations":
            continue
        if values is None and group not in p:
            continue
        page = "voices" if group in ("voices", "sounds", "voiceDeclarations") else group
        if not isinstance(values, list):
            invalid(page, "", group, group, "使用数组；没有记录时使用 []")
            continue
        for index, item in enumerate(values):
            path = f"{group}[{index}]"
            if not isinstance(item, dict):
                invalid(page, "", path, "声明记录", "每条记录必须是对象")
                continue
            rid = _text(item.get("id")) or _text(item.get("asset"))
            if group in ("animations", "effects"):
                flag_field(item, "includesCompanion", page, rid, path)
                enum_field(item, "origin", EFFECT_ORIGINS, page, rid, path)
                for key in ("purpose", "companionNote", "originNote"):
                    text_field(item, key, 500, page, rid, path)
            else:
                for key, limit in (("usage", 500), ("text", 2000)):
                    text_field(item, key, limit, page, rid, path)
                if group == "voiceDeclarations":
                    enum_field(item, "entry", VOICE_ENTRIES, page, rid, path)
                    flag_field(item, "reused", page, rid, path)
                    for key in ("id", "asset", "file"):
                        text_field(item, key, 500, page, rid, path)

    ui = p.get("uiDeclarations")
    if ui is not None and not isinstance(ui, dict):
        invalid("portraits", "", "uiDeclarations", "UI 声明", "使用 form:slot 为键的对象；未标注使用 {}")
    elif isinstance(ui, dict):
        for key, spec in ui.items():
            path = "uiDeclarations." + _text(key)
            parts = key.split(":") if isinstance(key, str) else []
            if len(parts) != 2 or parts[0] not in ("base", "evolved") or parts[1] not in UI_SLOTS:
                invalid("portraits", _text(key), path, "UI 用途", "键名必须是 base:槽位 或 evolved:槽位，且槽位是有效 UI 用途")
            if not isinstance(spec, dict):
                invalid("portraits", _text(key), path, "UI 声明记录", "使用含 autoCrop、mask、note 的对象")
                continue
            flag_field(spec, "autoCrop", "portraits", key, path)
            enum_field(spec, "mask", UI_MASK_VALUES, "portraits", key, path)
            text_field(spec, "note", 2000, "portraits", key, path)

    assets = p.get("assets", {})
    if isinstance(assets, dict):
        for aid, asset in assets.items():
            if not isinstance(asset, dict):
                continue  # General project validation owns the asset shape.
            enum_field(asset, "variant", ("plain", "composite", "effect", "ui", "unknown"),
                       "animations", aid, "assets." + _text(aid))
            text_field(asset, "sourceNote", 2000, "animations", aid, "assets." + _text(aid))
    return issues


def validate_declarations(p):
    if not isinstance(p, dict):
        raise StudioError("作者声明必须附在工程对象中")
    problems = declaration_errors(p)
    if problems:
        raise StudioError(problems[0]["text"])
    return p


def _path(value):
    return _text(value).replace("\\", "/").strip()


def _voice_aliases(p, voice):
    assets = p.get("assets", {})
    asset = assets.get(voice.get("asset"), {}) if isinstance(voice.get("asset"), str) else {}
    values = {_path(value) for value in (voice.get("id"), voice.get("asset"), voice.get("sourceFile"),
                                        voice.get("logical"), voice.get("name"), asset.get("name"), asset.get("file")) if _marked(value)}
    return values | {value.removeprefix("voice/") for value in values if value.startswith("voice/")}


_USAGE_ENTRY = {"join": "ally", "evolution": "ally", "home": "home", "login": "login", "story_words": "words",
                **{key: "battle" for key in ("battle_start", "skill_voice", "skill_ready", "power_flip", "attack", "outhole", "win", "battle")}}


def _voice_matches(p):
    """Resolve explicit references once for both reports and v1 export."""
    voices = _records(p, "voices")
    declarations = _records(p, "voiceDeclarations")
    aliases = [_voice_aliases(p, voice) for voice in voices]
    owners = {}
    for index, values in enumerate(aliases):
        for value in values:
            owners.setdefault(value, set()).add(index)
    matches = [[] for _ in voices]
    unmatched = []
    for index, declaration in enumerate(declarations):
        refs = [_path(declaration.get(key)) for key in ("id", "asset", "file") if _marked(declaration.get(key))]
        targets = [owners.get(ref, set()) for ref in refs]
        candidates = set.intersection(*targets) if targets else set()
        if len(candidates) == 1:
            matches[next(iter(candidates))].append(index)
        else:
            unmatched.append(index)
    return voices, matches, unmatched


def voice_table(p):
    """Join real voice records with declarations without confirming unknown fields."""
    voices, matches, unmatched = _voice_matches(p)
    declarations = _records(p, "voiceDeclarations")
    result = []
    for index, voice in enumerate(voices):
        matched = [declarations[i] for i in matches[index]]
        declared = matched[0] if len(matched) == 1 else {}
        asset = (p.get("assets") or {}).get(voice.get("asset"), {}) if isinstance(voice.get("asset"), str) else {}
        usage = _text(declared.get("usage")) if _marked(declared.get("usage")) else _text(voice.get("usage"))
        text = _text(declared.get("text")) if _marked(declared.get("text")) else _text(voice.get("text"))
        entry = _text(declared.get("entry"))
        if not entry:
            for path in (voice.get("sourceFile"), voice.get("logical"), asset.get("name")):
                parts = _path(path).split("/")
                if parts[0] == "voice":
                    parts = parts[1:]
                if parts and parts[0] in VOICE_ENTRIES:
                    entry = parts[0]
                    break
            entry = entry or _USAGE_ENTRY.get(usage, "")
        result.append({"id": _text(voice.get("id")), "asset": _text(voice.get("asset")),
                       "file": _text(voice.get("sourceFile") or asset.get("name") or voice.get("name")),
                       "entry": entry, "usage": usage, "text": text,
                       "reused": declared.get("reused") if type(declared.get("reused")) is bool else "",
                       "ambiguous": len(matched) > 1})
    return result, unmatched


def ui_table(p):
    from portrait_editor import selection, SLOT_SHAPES
    ui = p.get("uiDeclarations")
    ui = ui if isinstance(ui, dict) else {}
    # selection is a rendering helper, whose defaults are not author declarations.
    view = {**p, "uiDeclarations": {}}
    result = []
    for form in ("base", "evolved"):
        for slot in KEY_UI_SLOTS:
            key = form + ":" + slot
            selected = selection(view, form, slot)
            if not selected.get("asset"):
                continue
            spec = ui.get(key)
            spec = spec if isinstance(spec, dict) else {}
            needs_note = spec.get("autoCrop") is False or (spec.get("mask") == "none" and slot in SLOT_SHAPES)
            result.append({"key": key, "form": form, "slot": slot, "selection": selected,
                           "autoCrop": spec.get("autoCrop"), "mask": spec.get("mask"),
                           "note": _text(spec.get("note")), "needsNote": needs_note})
    return result


def declaration_report(p):
    """One source for declaration issues and applicable-check completion counts."""
    issues = declaration_errors(p)
    complete = total = 0

    def requirement(done):
        nonlocal complete, total
        total += 1
        complete += int(done)

    def add(code, level, page, text, rid, position, location, fix, blocking=False):
        issues.append(make_issue(code, level, page, text, id=rid, position=position,
                                location=location, fix=fix, blocking=blocking, declaration=True))

    from action_presets import ACTION_PRESETS
    preset_slots = {item["slot"] for item in ACTION_PRESETS}
    for anim in _records(p, "animations"):
        rid, slot = _text(anim.get("id")), _text(anim.get("slot"))
        name = _text(anim.get("name")) or slot or rid
        position = f"像素动作 → {name}（{slot}）"
        location = "animations." + rid
        variant = animation_variant(p, anim)
        composite = variant in ("composite", "mixed")
        companion = anim.get("includesCompanion")
        note = _marked(anim.get("companionNote"))
        base_risk = composite and slot in BASE_STATE_SLOTS and (companion is not True or not note)
        contradiction = composite and companion is False
        has_frames = bool(anim.get("clips") or anim.get("nativeFrames"))
        applicable = has_frames and (composite or slot in COMPANION_STATE_SLOTS or companion is True)
        if applicable:
            requirement(type(companion) is bool and not base_risk and not contradiction and (companion is False or note))
        if contradiction:
            add("companion_declaration_conflict", "warning", "animations",
                f"动作『{name}』实际引用合成帧，但声明不包含附属物", rid, position, location + ".includesCompanion",
                "替换为纯本体帧；或改为“是”并说明附属物的用途与出现时机", True)
        elif base_risk:
            add("base_state_composite_suspect", "warning", "animations",
                f"基础状态『{name}』引用合成帧，尚未明确允许并说明出现时机", rid, position, location + ".includesCompanion",
                "换为纯本体帧；确需附属物时必须选择“是”并填写附属物说明", True)
        if applicable and type(companion) is not bool:
            add("companion_undeclared", "todo", "animations", f"动作『{name}』尚未说明是否带召唤物/附属物", rid,
                position, location + ".includesCompanion", "在『是否包含召唤物』选择是/否；选择是时补充出现时机")
        elif applicable and companion is True and not note:
            add("companion_note_missing", "todo", "animations", f"动作『{name}』缺附属物说明", rid,
                position, location + ".companionNote", "说明附属物是什么、出现时机及合成帧用途")
        if variant == "mixed":
            add("frame_group_mixed", "warning", "animations", f"动作『{name}』同时选用了纯本体帧和合成帧", rid,
                position, location + ".clips", "核对所选帧顺序；只保留一套，或在附属物说明中说明混用的时机")
        if has_frames and slot not in preset_slots:
            done = _marked(anim.get("purpose"))
            requirement(done)
            if not done:
                add("animation_notes_missing", "todo", "animations", f"自定义动作『{name}』缺用途说明", rid,
                    position, location + ".purpose", "填写用途，并核对帧顺序、停留与循环方式")

    for effect in _records(p, "effects"):
        rid = _text(effect.get("id"))
        name = _text(effect.get("name")) or rid
        origin = effect.get("origin")
        done = isinstance(origin, str) and origin in EFFECT_ORIGINS and _marked(effect.get("originNote"))
        requirement(done)
        if not isinstance(origin, str) or origin not in EFFECT_ORIGINS:
            add("effect_origin_missing", "warning", "effects", f"技能特效『{name}』未声明有效来源", rid,
                "技能制作 → " + name, "effects." + rid + ".origin", "选择复用/重皮/原创，并写明来源角色、模板或四件套/骨架")
        elif not _marked(effect.get("originNote")):
            add("effect_origin_note_missing", "todo", "effects", f"技能特效『{name}』缺来源说明", rid,
                "技能制作 → " + name, "effects." + rid + ".originNote", "复用写来源角色/特效；重皮写模板与配色；原创写四件套或骨架来源")

    voices, unmatched = voice_table(p)
    for voice in voices:
        missing = [label for field, label in (("entry", "入口分类"), ("usage", "用途"), ("text", "台词")) if not _marked(voice[field])]
        done = not missing and not voice["ambiguous"]
        requirement(done)
        if missing or voice["ambiguous"]:
            reason = "存在重复登记" if voice["ambiguous"] else "缺少" + "、".join(missing)
            add("voice_usage_missing", "todo", "voices", f"语音『{voice['file'] or voice['id']}』{reason}", voice["id"],
                "声音与台词 → " + (voice["file"] or voice["id"]), "voices." + voice["id"],
                "补齐入口 ally/battle/home/login/words、用途、完整台词（无台词请写“暂无台词”）；每条语音只登记一次")
    for index in unmatched:
        add("voice_declaration_unmatched", "warning", "voices", "语音声明未能唯一对应工程语音", "",
            f"声音与台词 → 语音对照表第 {index + 1} 行", f"voiceDeclarations[{index}]",
            "使用实际语音 id/asset 或准确的源文件名，不要用无关或重复文件登记充数")

    for ui in ui_table(p):
        missing = []
        if type(ui["autoCrop"]) is not bool:
            missing.append("是否允许母版自动裁切")
        if not isinstance(ui["mask"], str) or ui["mask"] not in UI_MASK_VALUES:
            missing.append("遮罩意图")
        if ui["needsNote"] and not _marked(ui["note"]):
            missing.append("特殊取景/不使用官方形状的原因")
        requirement(not missing)
        if missing:
            label = ("基础" if ui["form"] == "base" else "进化") + " · " + UI_SLOTS[ui["slot"]][0]
            add("ui_special_crop_unmarked", "info", "portraits", f"『{label}』缺声明：{'、'.join(missing)}", ui["key"],
                "立绘与界面 → " + label, "uiDeclarations." + ui["key"],
                "逐形态填写 autoCrop（是/否）与 mask（auto/none/形状）；特殊取景或禁用官方形状时补说明")
    return {"issues": issues, "declarations": {"complete": complete, "total": total}, "voiceTable": voices}


def readiness(issues, declarations):
    counts = Counter(item["level"] for item in issues)
    blocking = sum(item["blocking"] is True for item in issues)
    pending = counts["todo"] or counts["warning"] or declarations["complete"] < declarations["total"]
    return {"canCompile": blocking == 0, "blocking": blocking,
            "todo": counts["todo"], "warning": counts["warning"], "info": counts["info"],
            "declarations": dict(declarations),
            "status": "blocked" if blocking else "needs_review" if pending else "ready"}


def _export_voice_declarations(p, rows):
    """Expose effective voice fields to v1 readers while retaining unresolved rows.

    A unique explicit declaration keeps its extra fields; missing fields use the
    same source evidence as the check report. Duplicate/unmatched declarations
    remain visible and are never silently merged into an attested record.
    """
    declared = copy.deepcopy(p["voiceDeclarations"])
    _, matches, _ = _voice_matches(p)
    fields = ("id", "asset", "file", "entry", "usage", "text", "reused")
    for row, matched in zip(rows, matches):
        if len(matched) > 1:
            continue
        resolved = {field: row[field] for field in fields}
        if matched:
            declared[matched[0]].update(resolved)
        else:
            declared.append(resolved)
    return declared


def declaration_payload(p):
    """Keep v1 fields compatible; add effective voice rows and asset evidence."""
    result = copy.deepcopy(p)
    normalize_declarations(result)
    validate_declarations(result)
    ui_declarations = copy.deepcopy(result["uiDeclarations"])
    for spec in ui_declarations.values():
        if spec.get("mask") == "":
            # v1 consumers accept an absent mask as unknown, not an invalid enum.
            spec.pop("mask")
    voices, _ = voice_table(result)
    return {"schema": "starpoint-character-studio-declarations-v1", "authorNotes": result["authorNotes"],
            "animations": [{"id": anim.get("id"), "name": anim.get("name"), "slot": anim.get("slot", ""),
                            "variant": animation_variant(result, anim), "includesCompanion": anim["includesCompanion"],
                            "companionNote": anim["companionNote"], "purpose": anim["purpose"]} for anim in result.get("animations", [])],
            "effects": [{key: effect.get(key, "") for key in ("id", "name", "origin", "originNote")} for effect in result.get("effects", [])],
            "uiDeclarations": ui_declarations,
            "voiceDeclarations": _export_voice_declarations(result, voices), "voiceTable": voices,
            "assets": [{"id": aid, "name": asset.get("name", ""), "variant": clip_variant(result, aid),
                        "declaredVariant": asset.get("variant", ""), "sourceNote": asset.get("sourceNote", "")}
                       for aid, asset in result.get("assets", {}).items()]}


def _md(value):
    """Escape author-controlled Markdown/HTML and keep multiline table cells."""
    value = html.escape(_text(value), quote=False).replace("\r\n", "\n").replace("\r", "\n")
    for char in ("\\", "|", "`", "*", "_", "[", "]", "#"):
        value = value.replace(char, "\\" + char)
    return value.replace("\n", "<br>")


def _bool_label(value):
    return "是" if value is True else "否" if value is False else "未标注" if _flag(value) else "无效（待修正）"


def author_readme(p, report=None):
    """Use the exact project_checks issue set, without mutating the project."""
    if report is None:
        from studio_core import project_checks
        report = project_checks(p)
    lines = ["# 稿主必读（角色工坊自动生成）", "",
             "这个包是可编辑创作工程或正式离线候选的交接材料，不是已完成游戏接入的补丁。",
             "源工程包可在工坊用「打开工程 / 参考包」继续制作；候选包仍需制作方接入与验收。", "",
             "角色：" + _md(p.get("name")), "作者：" + _md((p.get("identity") or {}).get("author")),
             "作者说明：" + (_md(p.get("authorNotes")) or "未标注"), "",
             "提交就绪状态：" + report["readiness"]["status"],
             "无编译阻断：" + ("是（不等于素材/声明完稿或游戏就绪）" if report["readiness"]["canCompile"] else "否（仍可保存和导出草稿）"), "",
             "## 1. 动作清单", "", "| 槽位 | 中文 | 画稿段数 | 总帧 | 播放 | 帧来源 | 包含召唤物 | 说明 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    variants = {"plain": "纯本体", "composite": "合成帧", "mixed": "纯本体+合成帧混用", "unknown": "未标注", "": "未标注"}
    play = {"once": "单次", "loop": "循环", "pass": "衔接下一段", "stop": "停在首帧"}
    for anim in _records(p, "animations"):
        clips = anim.get("clips") or []
        frames = len(anim.get("nativeFrames") or []) or sum(c.get("hold", 0) for c in clips if type(c.get("hold")) is int)
        values = (anim.get("slot", ""), anim.get("name") or LABELS.get(anim.get("slot"), ""), str(len(clips)), str(frames),
                  play.get(_text(anim.get("kind")), "未标注"), variants.get(animation_variant(p, anim), "未标注"),
                  _bool_label(anim.get("includesCompanion")), anim.get("companionNote") or anim.get("purpose") or "未标注")
        lines.append("| " + " | ".join(_md(v) for v in values) + " |")
    lines += ["", "## 2. 语音入口表", "", "| 文件/素材 | 入口 | 用途 | 台词 | 复用 |", "| --- | --- | --- | --- | --- |"]
    voices, unmatched = voice_table(p)
    for voice in voices:
        lines.append("| " + " | ".join(_md(voice[key] or "未标注") for key in ("file", "entry", "usage", "text")) + " | " + _bool_label(voice["reused"]) + " |")
    if not voices:
        lines.append("| （尚无工程语音） | 未标注 | 未标注 | 未标注 | 未标注 |")
    for index in unmatched:
        lines.append(f"- 对照表第 {index + 1} 行未能对应实际语音，不视为已登记。")
    lines += ["", "## 3. UI 用途声明", "", "| 用途 | 允许自动裁切 | 遮罩 | 说明 |", "| --- | --- | --- | --- |"]
    ui = p.get("uiDeclarations") if isinstance(p.get("uiDeclarations"), dict) else {}
    keys = {row["key"] for row in ui_table(p)} | {key for key in ui if isinstance(key, str)}
    for key in sorted(keys):
        spec = ui.get(key) if isinstance(ui.get(key), dict) else {}
        lines.append("| " + _md(key) + " | " + _bool_label(spec.get("autoCrop")) + " | " + _md(spec.get("mask") or "未标注") + " | " + _md(spec.get("note") or "未标注") + " |")
    if not keys:
        lines.append("| （尚无适用声明） | 未标注 | 未标注 | 未标注 |")
    lines += ["", "## 4. 特效来源声明", "", "| 特效 | 来源 | 来源说明 |", "| --- | --- | --- |"]
    for effect in _records(p, "effects"):
        lines.append("| " + " | ".join(_md(v) for v in (effect.get("name") or effect.get("id"), effect.get("origin") or "未标注", effect.get("originNote") or "未标注")) + " |")
    if not _records(p, "effects"):
        lines.append("| （尚未建立特效） | 未标注 | 未标注 |")
    lines += ["", "## 5. 未标注项清单与全部未解决项（与检查报告同源）", "",
              "以下包含阻断、待补、警告和游戏接入待办；未标注不等于已确认“否”。", "",
              "| code | 级别 | 阻断编译 | 位置 | 问题 | 怎么改 |", "| --- | --- | --- | --- | --- | --- |"]
    for issue in report["issues"]:
        values = (issue["level"], _bool_label(issue["blocking"]), issue["position"], issue.get("summary", issue["text"]), issue["fix"])
        lines.append("| `" + issue["code"] + "` | " + " | ".join(_md(v) for v in values) + " |")
    if not report["issues"]:
        lines.append("| — | — | 否 | — | 无 | — |")
    lines.append("")
    return "\n".join(lines)
