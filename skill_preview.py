"""Bounded, offline staging of the deterministic visual subset of ActionDSL.

The original tree remains the source of truth. This is deliberately not a battle
evaluator: callbacks needing collisions/targets stay deferred and are reported.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import PurePosixPath

LIMIT = 4096
MAX_TRACKS = 384


def length(animation):
    return len(animation.get("nativeFrames", [])) or sum(c["hold"] for c in animation.get("clips", []))


def track(kind, ref, start=0, **values):
    return dict(id="track_" + hashlib.sha256(f"{kind}:{ref}:{start}:{values}".encode()).hexdigest()[:16],
                type=kind, ref=ref, start=start, x=0, y=0, scale=1, rotation=0,
                opacity=1, volume=1, speed=1, visible=True, **values)


def effect_path(logical):
    directory, name = logical.rsplit("/", 1)
    folder = directory.rsplit("/", 1)[-1] + "_" + hashlib.sha256(directory.encode()).hexdigest()[:8]
    return f"effect/{folder}/decoded/{name}.parts.json"


def plan_program(project, program, index=0):
    tracks, notes, deferred, hides, effect_hides, instances = [], set(), [], [], [], []
    effects = project.get("effects", [])
    by_path = {}
    for effect in effects:
        if length(effect):
            by_path.setdefault(effect.get("native", {}).get("path"), []).append(effect)
    for choices in by_path.values():
        choices.sort(key=lambda a: a.get("native", {}).get("begin", LIMIT + 1))
    visits = 0
    cancelled_labels = set()
    def scan_cancellations(node, pointer=""):
        if not isinstance(node, list):
            return
        if node and node[0] == "RemoveEvent" and len(node) > 1 and isinstance(node[1], str):
            cancelled_labels.add(node[1])
        if node and node[0] in ("GenericHealHitEffect", "GenericConditionHitEffect"):
            notes.add("治疗、状态变化等系统反馈尚未模拟；这类效果没有独立角色特效素材。")
            deferred.append(dict(reason="系统治疗或状态反馈尚未模拟", pointer=pointer, command=node[0]))
        for i, item in enumerate(node):
            scan_cancellations(item, pointer + f"/{i}")
    scan_cancellations(program.get("tree", []))

    def numeric(value, default=0):
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            return float(value)
        if isinstance(value, list) and value:
            if value[0] == "None":
                return default
            if value[0] == "Some":
                return numeric(value[1], default)
            if all(isinstance(term, dict) for term in value):
                if any(term.get("mul") is not None or term.get("vlv") or any(term.get(key) is not None for key in ("alv", "alv2", "alv3", "alv4", "alv5", "alv6")) for term in value):
                    notes.add("部分参数依赖能力等级或战斗变量，暂用固定演示值。")
                    return default
                if any(term.get("min") != term.get("max") for term in value):
                    notes.add("随技能等级变化的参数采用首档数值；可在轨道中调整。")
                return sum(numeric(term["min"]) for term in value if term.get("min") is not None and term.get("max") is not None)
        notes.add("部分数值依赖战斗变量，暂用固定演示值。")
        return default

    def point(subject, coord, u, v, env):
        if subject not in env:
            notes.add("部分效果依赖目标位置，当前固定在预览原点。")
        x, y = env.get(subject, (0, 0))
        if coord != ["AB"]:
            notes.add("依赖角色或目标方向的坐标采用固定朝向，未模拟追踪。")
        return (max(-4096, min(4096, x + numeric(u))), max(-4096, min(4096, y + numeric(v))))

    def has_visual(node):
        if not isinstance(node, list):
            return False
        return bool(node and isinstance(node[0], str) and node[0] in ("ShowEffect", "SpecifyEffectDirectly", "SpecifyEffectWithElement")) or any(has_visual(v) for v in node)

    def add_effect(command, tick, pointer, env):
        if len(command) < 13 or len(tracks) >= MAX_TRACKS:
            notes.add("演出条目超出解析范围，请查看各阶段素材。")
            return
        ref = command[2]
        logical = None
        if ref[0] == "SpecifyEffectDirectly":
            logical = ref[1]
        elif ref[0] == "ResolveByElement" and len(ref) == 3:
            colors = ("red", "blue", "yellow", "green", "white", "black", "colorless")
            current_element = ("火", "水", "雷", "风", "光", "暗").index(project.get("identity", {}).get("element", "火"))
            resolved = current_element if ref[2] == 255 else ref[2] - 1
            if 0 <= resolved < len(colors):
                name = ref[1].rsplit("/", 1)[-1] + "_" + colors[resolved]
                logical = f"{ref[1]}/{name}/{name}"
        choices = by_path.get(effect_path(logical), []) if logical and "/" in logical else []
        if not choices:
            deferred.append(dict(reason="对应特效未能匹配到可播放素材", pointer=pointer, resource=logical or str(ref)))
            return
        # A playhead advances in global frame coordinates, not array order.
        # Snapping effects replace direction sequences and never fade to end.
        names = {a.get("native", {}).get("sequence") for a in choices}
        snapping = {"normal", "angle_45"} <= names
        effect = next(a for a in choices if a["native"]["sequence"] == "normal") if snapping else choices[0]
        if snapping:
            notes.add("方向特效固定使用正向序列；不同角度是替代关系，未模拟方向切换。")
        life = command[5]
        natural = max(1, length(effect))
        if life[0] == "PlayOnlyFirstSequence":
            life_ticks = natural
        elif life[0] in ("SpecifyEffectLifetimeDirectly", "SpecifyEffectLifetimeSLv"):
            life_ticks = max(1, math.ceil(numeric(life[1], natural)))
        else:
            life_ticks = natural
            notes.add("部分效果持续到目标或状态结束；此处先播放一个素材周期。")
        x, y = point(command[3], command[6], command[7], command[8], env)
        if command[10] or command[11]:
            notes.add("角色、目标与场地使用固定演示位置；移动和追踪未模拟。")
        value = track("effect", effect["id"], tick, end=min(LIMIT, tick + life_ticks),
                      label=command[1], source={"pointer": pointer, "resource": logical, "command": "ShowEffect"})
        # Animation.scale starts at parts.s; ShowEffect Some(scale) replaces it.
        # Editor tracks multiply the asset's scale, hence convert the override.
        native_scale = effect.get("frameScale", 1) or 1
        ratio = numeric(command[12], native_scale) / native_scale
        if not .05 <= ratio <= 20:
            notes.add("个别脚本缩放超出当前轨道范围，已限制；请在特效编辑中调整基础倍率。")
        value.update(x=x, y=y, rotation=((numeric(command[9]) * 180 / math.pi + 180) % 360) - 180,
                     scale=max(.05, min(20, ratio)),
                     layer=command[4][0])
        value["source"]["order"] = visits
        value["instanceId"] = value["id"]
        instance = dict(id=value["id"], start=tick, end=value["end"], label=command[1], order=visits)
        instances.append(instance)
        current, cursor, phase_index = effect, tick, 0
        while cursor < instance["end"] and len(tracks) < MAX_TRACKS:
            kind = current.get("kind", "once")
            phase_end = min(instance["end"], cursor + length(current)) if kind == "pass" else instance["end"]
            phase = dict(value, id=value["id"] if phase_index == 0 else value["id"] + f"_phase_{phase_index}",
                         ref=current["id"], start=cursor, end=phase_end, playMode=kind,
                         source={**value["source"], "sequence": current.get("native", {}).get("sequence")})
            if phase_index:
                phase["phaseOf"] = value["id"]
                phase["label"] = str(command[1]) + " · " + current.get("native", {}).get("sequence", "后续阶段")
                native_scale = current.get("frameScale", 1) or 1
                phase["scale"] = max(.05, min(20, numeric(command[12], native_scale) / native_scale))
            tracks.append(phase)
            if kind != "pass" or phase_end >= instance["end"]:
                break
            native_end = current.get("native", {}).get("end")
            successors = [a for a in choices if native_end is not None and a.get("native", {}).get("begin") == native_end + 1]
            if snapping or len(successors) != 1:
                notes.add("部分连续特效缺少唯一的相邻序列或依赖方向切换，剩余寿命未自动展开。")
                deferred.append(dict(reason="连续序列不能确定，已保留可确认阶段", pointer=pointer, resource=logical))
                break
            current, cursor, phase_index = successors[0], phase_end, phase_index + 1
        if len(tracks) >= MAX_TRACKS:
            notes.add("演出条目超出解析范围，请查看各阶段素材。")
        ending = None if snapping else next((a for a in choices if a.get("native", {}).get("sequence") == "end"), None)
        if ending and ending["id"] != effect["id"] and tick + life_ticks < LIMIT:
            finish = dict(value, id=value["id"] + "_end", ref=ending["id"], start=tick + life_ticks,
                          end=min(LIMIT, tick + life_ticks + length(ending)), label=str(command[1]) + " · 收尾",
                          endingOf=value["id"], playMode=ending.get("kind", "once"),
                          source={**value["source"], "sequence": "end"})
            tracks.append(finish)

    def walk(node, tick=0, pointer="", env=None, depth=0):
        nonlocal visits
        visits += 1
        if visits > 20000 or depth > 60 or tick >= LIMIT or len(tracks) >= MAX_TRACKS:
            notes.add("超长或密集演出已限制展开范围；剩余阶段可单独试看。")
            return
        if not isinstance(node, list) or not node:
            return
        tag = node[0]
        if not isinstance(tag, str):
            return
        env = {-18: (0, 0), -17: (0, 0), -1: (0, 0)} if env is None else env
        def sub(value, at=tick, suffix="", context=env):
            walk(value, at, pointer + suffix, context, depth + 1)
        if tag == "ActionDsl":
            for i, child in enumerate(node[1:], 1):
                if isinstance(child, list) and child and child[0] == "Block":
                    sub(child, suffix=f"/{i}")
        elif tag == "Block":
            for i, child in enumerate(node[1]):
                sub(child, suffix=f"/1/{i}")
        elif tag in ("Command", "Event"):
            sub(node[1], suffix="/1")
        elif tag == "Wait" and len(node) >= 4:
            if node[2] in cancelled_labels:
                notes.add("存在取消事件指令，相关事件暂未自动排入，避免播放已取消的阶段。")
                if has_visual(node):
                    deferred.append(dict(reason="事件可能被取消", pointer=pointer))
            else:
                sub(node[3], tick + max(0, math.ceil(numeric(node[1]))), "/3")
        elif tag == "Repeat" and len(node) >= 5:
            if node[3] in cancelled_labels:
                notes.add("存在取消事件指令，相关重复事件暂未自动排入。")
                if has_visual(node):
                    deferred.append(dict(reason="重复事件可能被取消", pointer=pointer))
                return
            count, interval = max(0, int(numeric(node[2]))), max(1, int(numeric(node[1], 1)))
            if count > 128:
                notes.add("重复事件最多展开 128 次。")
            for n in range(min(count, 128)):
                sub(node[4], tick + n * interval, "/4")
        elif tag == "ShowEffect":
            add_effect(node, tick, pointer, env)
        elif tag == "HideCharacter" and len(node) >= 3:
            if node[1] in (-17, -18):
                hides.append((tick, min(LIMIT, tick + max(1, int(numeric(node[2], 1))))))
        elif tag == "HideEffect":
            effect_hides.append((tick, visits, node[1]))
        elif tag == "CreateHitArea" and len(node) > 23:
            context = dict(env)
            context[node[19]] = point(node[2], node[3], node[4], node[5], env)
            if node[12] != ["Single"]:
                notes.add("多目标或阵列判定使用一个固定演示位置。")
            sub(node[20], suffix="/20", context=context)
            if has_visual(node[23]):
                deferred.append(dict(reason="命中后才播放，需要战斗目标与命中时机", pointer=pointer + "/23"))
        elif tag == "CreateReferencePoint" and len(node) > 11:
            context = dict(env)
            context[node[9]] = point(node[1], node[2], node[3], node[4], env)
            if node[8] != ["Single"]:
                notes.add("阵列参考点暂以一个固定位置演示。")
            sub(node[11], suffix="/11", context=context)
        elif tag == "CreateReferencePointAtSpecifiedPosition" and len(node) > 5:
            notes.add("指定场地参考点使用固定演示位置。")
            sub(node[5], suffix="/5")
        elif tag in ("MoveBall", "MoveHitArea", "RotateHitArea", "ShakeCamera"):
            notes.add("战斗移动、镜头与命中判定未模拟。")
        elif tag in ("FindNearSubjects", "FindAllSubjects"):
            notes.add("依赖目标查询的操作尚未模拟。")
            if has_visual(node):
                deferred.append(dict(reason="需要查询战斗目标后触发", pointer=pointer, command=tag))
        elif has_visual(node):
            deferred.append(dict(reason="需要目标、条件或其他战斗逻辑触发", pointer=pointer, command=tag))

    walk(program.get("tree", []))
    # Scheduling order in the source tree is not execution time. Resolve hides
    # only after all timed commands are collected, and move the native end phase.
    for tick, order, label in sorted(effect_hides):
        for instance in instances:
            if instance["label"] != label:
                continue
            if (instance["start"], instance["order"]) <= (tick, order) and tick < instance["end"]:
                instance["end"] = tick
                for value in tracks:
                    if value.get("instanceId") == instance["id"] and not value.get("endingOf"):
                        value["end"] = min(value["end"], tick)
                ending = next((t for t in tracks if t.get("endingOf") == instance["id"]), None)
                if ending:
                    end_length = ending["end"] - ending["start"]
                    ending.update(start=tick, end=min(LIMIT, tick + end_length))
    tracks = [t for t in tracks if t["start"] < t["end"]]
    duration = min(LIMIT, max([120] + [t["end"] for t in tracks] + [end + 30 for _, end in hides]))
    actor = next((a for a in project.get("animations", []) if a.get("slot") == "neutral" and length(a)), None)
    actor_tracks = []
    if actor:
        cursor = 0
        for begin, end in sorted(hides) + [(duration, duration)]:
            if begin > cursor:
                actor_tracks.append(track("actor", actor["id"], cursor, end=min(begin, duration), label="角色位置参照 · 待机"))
            cursor = max(cursor, end)
    rank = {"BacksideOfCharacter": 0, "SameAsCharacter": 1, "ForesideOfCharacter": 2, "SuperForesideOfCharacter": 3, "NonPixelArt": 4}
    tracks = sorted(tracks + actor_tracks, key=lambda t: rank.get(t.get("layer"), 1))
    return {"id": f"program_{index}", "name": f"技能版本 {index + 1}", "program": program.get("logical", ""),
            "visualEvents": sum(t["type"] == "effect" for t in tracks), "notes": sorted(notes), "deferred": deferred[:100],
            "scene": {"duration": duration, "tracks": tracks, "source": {"kind": "official-script", "program": program.get("logical", ""),
                        "label": "按官方脚本时序演示", "notes": sorted(notes), "deferredCount": len(deferred)}}}


def preview_plans(store, pid):
    project = store.load(pid)
    # Older projects did not retain sequence coordinates. Enrich only the
    # loaded copy from its own reference files; opening never saves a project.
    reference = (store.directory(pid) / "reference").resolve()
    metadata = {}
    for effect in project.get("effects", []):
        native = effect.get("native", {})
        if not native.get("path") or ("begin" in native and "end" in native):
            continue
        logical = native["path"].replace(".parts.json", ".timeline.json")
        if logical not in metadata:
            timeline = (reference / logical).resolve()
            try:
                timeline.relative_to(reference)
                metadata[logical] = json.loads(timeline.read_text("utf-8")) if timeline.is_file() else {}
            except (ValueError, OSError):
                metadata[logical] = {}
        sequence = next((s for s in metadata[logical].get("sequences", []) if s.get("name") == native.get("sequence")), None)
        if sequence:
            native.update(begin=sequence["begin"], end=sequence["end"])
    path = store.directory(pid) / "reference" / "data_readable" / "skill_dependencies.json"
    if not path.is_file():
        return {"programs": [], "message": "没有官方技能脚本参考；可以从动作和特效开始制作。"}
    data = json.loads(path.read_text("utf-8"))
    return {"programs": [plan_program(project, program, i) for i, program in enumerate(data.get("programs", [])[:32])],
            "message": "依据原始技能脚本的确定时序生成，采用固定演示位置。"}
